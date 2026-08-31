import json
import os
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import repository
from ..ai.local_model import (
    LocalModelError,
    ask_local_model,
    extract_json_block,
    is_configured,
    stream_local_model,
)
from ..execution.base import OrderExecutionError
from .analytics import build_portfolio_risk

router = APIRouter()


@router.get("/agent/status")
def get_agent_status():
    provider = os.getenv("AI_PROVIDER", "").strip()
    model = os.getenv("AI_MODEL", "").strip()
    model_connected = bool(provider and model)
    auto_execution_enabled = model_connected and os.getenv("AI_AUTO_EXECUTION_ENABLED", "false").lower() in {"1", "true", "yes"}
    return {
        "model_connected": model_connected,
        "provider": provider or None,
        "model": model or None,
        "execution_mode": "paper_auto" if auto_execution_enabled else "observe",
        "auto_execution_enabled": auto_execution_enabled,
        "safety": {
            "max_position_pct": float(os.getenv("AI_MAX_POSITION_PCT", "20")),
            "max_daily_loss_pct": float(os.getenv("AI_MAX_DAILY_LOSS_PCT", "3")),
            "human_approval_required": os.getenv("AI_HUMAN_APPROVAL_REQUIRED", "true").lower() not in {"0", "false", "no"},
        },
    }


class AgentRunRequest(BaseModel):
    candidates: list[str]
    decisions: list[dict]
    reasoning: str
    order_ids: list[int]


@router.get("/agent/candidates")
def get_agent_candidates(request: Request):
    return repository.get_candidates(request.app.state.conn)


@router.post("/agent/runs")
def create_agent_run(req: AgentRunRequest, request: Request):
    run_id = repository.insert_agent_run(
        request.app.state.conn,
        candidates=json.dumps(req.candidates, ensure_ascii=False),
        decisions=json.dumps(req.decisions, ensure_ascii=False),
        reasoning=req.reasoning,
        order_ids=json.dumps(req.order_ids),
    )
    return {"id": run_id}


@router.get("/agent/runs")
def list_agent_runs(request: Request):
    runs = repository.get_agent_runs(request.app.state.conn)
    return [
        {
            "id": run["id"],
            "ts": run["ts"],
            "candidates": json.loads(run["candidates"]),
            "decisions": json.loads(run["decisions"]),
            "reasoning": run["reasoning"],
            "order_ids": json.loads(run["order_ids"]),
        }
        for run in runs
    ]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    prompt: str
    scope: str = ""
    stock_code: str | None = None
    history: list[ChatMessage] = []


def _daily_loss_pct(conn, current_total_value: float) -> float | None:
    today = datetime.now(timezone.utc).date().isoformat()
    todays_snapshots = [s for s in repository.get_snapshots(conn) if s["ts"].startswith(today)]
    if not todays_snapshots or not todays_snapshots[0]["total_value"]:
        return None
    start_value = todays_snapshots[0]["total_value"]
    return (current_total_value - start_value) / start_value * 100


_SYSTEM_PROMPT = (
    "너는 한국 주식(KOSPI/KOSDAQ) 모의투자 계좌를 운용하는 AI 트레이딩 코파일럿이다. "
    "실제 돈이 아닌 모의투자 계좌이니 자율적으로 판단해도 된다. "
    "이전 대화 맥락을 기억하고 이어서 답해라. "
    "사용자 질문에 한국어로 간결하게 답하고, 필요하면 매수/매도 제안을 포함해라. "
    "응답 마지막에 다음 형식의 JSON 블록을 반드시 포함해라 (제안이 없으면 decisions는 빈 배열):\n"
    '```json\n{"decisions": [{"code": "종목코드", "action": "buy|sell", "quantity": 정수, "reason": "이유"}]}\n```'
)


def _build_prompt(conn, risk: dict, candidates: list[dict], req: ChatRequest) -> str:
    context_lines = [
        f"현재 화면: {req.scope or '전체'}",
        f"총자산: {risk['total_value']:.0f}원, 현금: {risk['cash']:.0f}원, 투자비중: {risk['invested_ratio_pct']:.1f}%",
        f"누적수익률: {risk['total_return_pct']:.2f}%, 최대낙폭: {risk['max_drawdown_pct']:.2f}%, 최대종목비중: {risk['max_position_weight_pct']:.1f}%",
        "보유종목: "
        + (
            ", ".join(f"{p['code']} {p['quantity']}주 평단{p['avg_price']:.0f}" for p in risk["positions"])
            or "없음"
        ),
        "매매후보(상위20): "
        + (
            ", ".join(
                f"{c['code']}({c['name']}) {c['change_pct']:.2f}%"
                if c["change_pct"] is not None
                else f"{c['code']}({c['name']})"
                for c in candidates
            )
            or "없음"
        ),
    ]
    if req.stock_code:
        context_lines.append(f"사용자가 보고 있는 종목: {req.stock_code}")

    history_lines = [
        f"{'사용자' if turn.role == 'user' else 'AI'}: {turn.content}" for turn in req.history[-6:]
    ]
    if history_lines:
        context_lines.append("이전 대화:\n" + "\n".join(history_lines))

    return "\n".join(context_lines) + f"\n\n사용자 질문: {req.prompt}"


def _execute_decisions(conn, provider, executor, decisions: list[dict], risk: dict) -> tuple[list[int], list[dict]]:
    auto_execution_enabled = os.getenv("AI_AUTO_EXECUTION_ENABLED", "false").lower() in {"1", "true", "yes"}
    if not auto_execution_enabled:
        return [], []

    max_position_pct = float(os.getenv("AI_MAX_POSITION_PCT", "20"))
    max_daily_loss_pct = float(os.getenv("AI_MAX_DAILY_LOSS_PCT", "3"))
    daily_loss = _daily_loss_pct(conn, risk["total_value"])
    daily_loss_breached = daily_loss is not None and daily_loss <= -max_daily_loss_pct

    executed_order_ids: list[int] = []
    blocked: list[dict] = []

    for decision in decisions:
        code = decision.get("code")
        action = decision.get("action")
        quantity = decision.get("quantity")
        if not code or action not in ("buy", "sell") or not isinstance(quantity, int) or quantity <= 0:
            blocked.append({"decision": decision, "reason": "invalid decision shape"})
            continue
        if action == "buy" and daily_loss_breached:
            blocked.append({"decision": decision, "reason": f"일일 손실 한도({max_daily_loss_pct}%) 초과, 매수 차단"})
            continue
        if action == "buy" and risk["total_value"]:
            try:
                price = provider.get_latest_price(code)
            except Exception:
                price = None
            if price is not None and (price * quantity) / risk["total_value"] * 100 > max_position_pct:
                blocked.append({"decision": decision, "reason": f"종목당 최대비중({max_position_pct}%) 초과"})
                continue
        try:
            result = executor.place_order(code, action, quantity)
            executed_order_ids.append(result.order_id)
        except OrderExecutionError as exc:
            blocked.append({"decision": decision, "reason": str(exc)})

    return executed_order_ids, blocked


@router.post("/agent/chat")
def agent_chat(req: ChatRequest, request: Request):
    if not is_configured():
        raise HTTPException(status_code=503, detail="로컬 모델이 연결되어 있지 않습니다 (AI_PROVIDER/AI_MODEL 미설정)")

    conn = request.app.state.conn
    provider = request.app.state.provider
    executor = request.app.state.executor

    risk = build_portfolio_risk(conn, provider)
    candidates = repository.get_candidates(conn)[:20]
    user_prompt = _build_prompt(conn, risk, candidates, req)

    try:
        raw = ask_local_model(_SYSTEM_PROMPT, user_prompt)
    except LocalModelError as exc:
        raise HTTPException(status_code=502, detail=f"로컬 모델 호출 실패: {exc}")
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"로컬 모델 연결 실패: {exc}")

    parsed = extract_json_block(raw) or {}
    decisions = parsed.get("decisions") or []
    answer = raw.split("```json")[0].strip() or raw.strip()

    executed_order_ids, blocked = _execute_decisions(conn, provider, executor, decisions, risk)

    repository.insert_agent_run(
        conn,
        candidates=json.dumps([c["code"] for c in candidates], ensure_ascii=False),
        decisions=json.dumps(decisions, ensure_ascii=False),
        reasoning=answer,
        order_ids=json.dumps(executed_order_ids),
    )

    return {
        "answer": answer,
        "decisions": decisions,
        "order_ids": executed_order_ids,
        "blocked": blocked,
    }


@router.post("/agent/chat/stream")
def agent_chat_stream(req: ChatRequest, request: Request):
    if not is_configured():
        raise HTTPException(status_code=503, detail="로컬 모델이 연결되어 있지 않습니다 (AI_PROVIDER/AI_MODEL 미설정)")

    conn = request.app.state.conn
    provider = request.app.state.provider
    executor = request.app.state.executor

    risk = build_portfolio_risk(conn, provider)
    candidates = repository.get_candidates(conn)[:20]
    user_prompt = _build_prompt(conn, risk, candidates, req)

    def generate():
        raw = ""
        try:
            for chunk in stream_local_model(_SYSTEM_PROMPT, user_prompt):
                raw += chunk
                yield chunk
        except (LocalModelError, requests.RequestException) as exc:
            yield f"\n[로컬 모델 오류: {exc}]"
            return

        parsed = extract_json_block(raw) or {}
        decisions = parsed.get("decisions") or []
        answer = raw.split("```json")[0].strip() or raw.strip()
        executed_order_ids, blocked = _execute_decisions(conn, provider, executor, decisions, risk)

        repository.insert_agent_run(
            conn,
            candidates=json.dumps([c["code"] for c in candidates], ensure_ascii=False),
            decisions=json.dumps(decisions, ensure_ascii=False),
            reasoning=answer,
            order_ids=json.dumps(executed_order_ids),
        )

        meta = json.dumps({"order_ids": executed_order_ids, "blocked": blocked}, ensure_ascii=False)
        yield f"\n<<<COPILOT_META>>>{meta}"

    return StreamingResponse(generate(), media_type="text/plain")
