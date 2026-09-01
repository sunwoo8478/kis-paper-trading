import re

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ..execution.base import OrderExecutionError
from ..execution.kis_paper_executor import KisPaperExecutor
from ..integrations.kis import KisApiError
from .. import repository

router = APIRouter()

_QUANTITY_PATTERN = re.compile(r"(\d+)\s*주")
_BUY_MARKERS = ("사줘", "사고싶", "사자", "매수해줘", "매수해", "매수하고싶", "매수하자")
_SELL_MARKERS = ("팔아줘", "팔고싶", "팔자", "매도해줘", "매도해", "매도하고싶", "매도하자")


class KisOrderRequest(BaseModel):
    code: str
    side: str
    quantity: int
    order_type: str = "market"
    limit_price: float | None = None


class KisChatRequest(BaseModel):
    prompt: str


@router.get("/kis/status")
def kis_status(request: Request, verify: bool = Query(default=False)):
    return request.app.state.kis_client.status(verify=verify)


@router.get("/kis/quote/{code}")
def kis_quote(code: str, request: Request):
    try:
        return request.app.state.kis_client.get_quote(code.strip().upper())
    except (KisApiError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/kis/balance")
def kis_balance(request: Request):
    try:
        return request.app.state.kis_client.get_balance()
    except KisApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/kis/buying-power")
def kis_buying_power(
    request: Request,
    code: str = Query(default="005930"),
    price: float | None = Query(default=None),
):
    try:
        return request.app.state.kis_client.get_buying_power(
            code.strip().upper(),
            price,
        )
    except (KisApiError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/kis/autonomous/status")
def kis_autonomous_status(request: Request):
    return request.app.state.kis_autonomous_engine.status()


@router.post("/kis/autonomous/start")
def kis_autonomous_start(request: Request):
    try:
        request.app.state.kis_autonomous_engine.set_enabled(True)
    except KisApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return request.app.state.kis_autonomous_engine.status()


@router.post("/kis/autonomous/stop")
def kis_autonomous_stop(request: Request):
    request.app.state.kis_autonomous_engine.set_enabled(False)
    return request.app.state.kis_autonomous_engine.status()


@router.post("/kis/autonomous/run")
def kis_autonomous_run(request: Request):
    return request.app.state.kis_autonomous_engine.run_cycle()


@router.get("/kis/autonomous/cycles")
def kis_autonomous_cycles(request: Request, limit: int = Query(default=30)):
    return repository.get_kis_paper_cycles(
        request.app.state.conn,
        max(1, min(limit, 200)),
    )


@router.get("/kis/orders")
def kis_orders(request: Request, limit: int = Query(default=100)):
    return repository.get_kis_paper_orders(
        request.app.state.conn,
        max(1, min(limit, 500)),
    )


@router.get("/kis/history")
def kis_history(request: Request, limit: int = Query(default=1000)):
    return repository.get_kis_paper_snapshots(
        request.app.state.conn,
        max(1, min(limit, 5000)),
    )


@router.get("/kis/broker-orders")
def kis_broker_orders(request: Request):
    try:
        orders = request.app.state.kis_client.get_daily_orders()
    except KisApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    for order in orders:
        repository.reconcile_kis_paper_order(request.app.state.conn, order)
    return orders


@router.post("/kis/orders")
def kis_place_order(req: KisOrderRequest, request: Request):
    executor = KisPaperExecutor(request.app.state.kis_client, request.app.state.conn)
    try:
        result = executor.place_order(
            req.code, req.side, req.quantity, req.order_type, req.limit_price,
            reason="사용자 수동 주문",
        )
    except (OrderExecutionError, KisApiError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "order_id": result.order_id,
        "broker_order_id": result.broker_order_id,
        "code": result.code,
        "side": result.side,
        "quantity": result.quantity,
        "status": result.status,
        "order_type": result.order_type,
        "limit_price": result.limit_price,
    }


@router.post("/kis/chat")
def kis_chat(req: KisChatRequest, request: Request):
    conn = request.app.state.conn
    normalized = "".join(req.prompt.split())
    stocks = repository.find_stocks_in_text(conn, req.prompt, limit=1)
    quantity_match = _QUANTITY_PATTERN.search(req.prompt)

    side = None
    if any(marker in normalized for marker in _SELL_MARKERS):
        side = "sell"
    elif any(marker in normalized for marker in _BUY_MARKERS):
        side = "buy"

    if not stocks or not quantity_match or side is None:
        return {
            "answer": "종목명(또는 코드), 수량, 매수/매도를 포함해서 말해주세요. 예: '삼성전자 10주 사줘'",
            "proposal": None,
        }

    stock = stocks[0]
    quantity = int(quantity_match.group(1))
    side_label = "매수" if side == "buy" else "매도"
    return {
        "answer": (
            f"{stock['name']}({stock['code']}) {quantity}주 {side_label} 제안입니다. "
            "확인을 누르면 KIS 모의투자 계좌로 시장가 주문이 전송됩니다."
        ),
        "proposal": {"code": stock["code"], "name": stock["name"], "side": side, "quantity": quantity},
    }
