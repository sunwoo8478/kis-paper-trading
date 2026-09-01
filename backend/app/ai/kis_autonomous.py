import json
import math
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import repository
from ..analytics import calculate_stock_analytics
from ..execution.base import OrderExecutionError
from ..execution.kis_paper_executor import KisPaperExecutor
from ..integrations.kis import KisApiError, KisPaperClient
from .autonomous import AutonomousTradingEngine, is_regular_market_open
from .competition import (
    competition_market_regime,
    competition_target_exposure_pct,
    position_target_pct,
    rank_competition_candidates,
)
from .local_model import ask_local_model, extract_json_block, is_configured


_SYSTEM_PROMPT = (
    "너는 한국투자증권 대회형 모의계좌의 자율 운용 판단 모듈이다. "
    "제공된 계좌와 후보 데이터 안에서만 판단하고 종목이나 가격을 추측하지 마라. "
    "손실 제한과 분산을 우선하고 마지막에 반드시 "
    '```json\n{"decisions":[{"code":"종목코드","action":"buy|sell","reason":"근거"}]}\n```'
    " 형식으로 응답하라."
)


class KisPaperAutonomousEngine:
    def __init__(self, db_path: str, provider, client: KisPaperClient):
        self.db_path = db_path
        self.provider = provider
        self.client = client
        self.interval_seconds = max(
            60,
            int(os.getenv("KIS_PAPER_AUTONOMOUS_INTERVAL_SECONDS", "300")),
        )
        self._owner_id = str(uuid.uuid4())
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._cycle_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_market_data_refresh_date: str | None = None
        self._runtime = {
            "running": False,
            "phase": "starting",
            "last_cycle_at": None,
            "last_error": None,
            "market_data_as_of": None,
        }
        with self._connection() as conn:
            enabled = os.getenv("KIS_PAPER_AUTONOMOUS_ENABLED", "false").lower() in {
                "1", "true", "yes"
            }
            repository.ensure_kis_paper_control(conn, enabled)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name="kis-paper-autonomous",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=15)

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            status = self.client.status()
            if not status["account_configured"] or not status["order_enabled"]:
                raise KisApiError("KIS 계좌 설정과 주문 활성화가 필요합니다")
        with self._connection() as conn:
            repository.set_kis_paper_enabled(conn, enabled)
        self._wake.set()

    def status(self) -> dict:
        with self._connection() as conn:
            control = repository.get_kis_paper_control(conn)
            cycles = repository.get_kis_paper_cycles(conn, 1)
        with self._state_lock:
            runtime = dict(self._runtime)
        next_cycle = None
        if control["enabled"] and runtime["last_cycle_at"]:
            last = datetime.fromisoformat(runtime["last_cycle_at"])
            next_cycle = (last + timedelta(seconds=self.interval_seconds)).isoformat()
        return {
            **runtime,
            **control,
            "execution_mode": "kis-paper",
            "strategy_mode": os.getenv("KIS_PAPER_STRATEGY_MODE", "standard"),
            "market_open": is_regular_market_open(),
            "interval_seconds": self.interval_seconds,
            "next_cycle_at": next_cycle,
            "broker": self.client.status(),
            "latest_cycle": cycles[0] if cycles else None,
        }

    def run_cycle(self, now: datetime | None = None) -> dict:
        if not self._cycle_lock.acquire(blocking=False):
            return {"status": "already_running", "broker_order_ids": []}
        with self._connection() as conn:
            lease = repository.acquire_kis_paper_lease(
                conn,
                self._owner_id,
                max(self.interval_seconds, 180),
            )
        if not lease:
            self._cycle_lock.release()
            return {"status": "lease_held", "broker_order_ids": []}

        started_at = datetime.now(timezone.utc).isoformat()
        market_open = is_regular_market_open(now)
        status = "market_closed"
        error = None
        market_regime = "market_closed" if not market_open else "unavailable"
        target_exposure_pct = 0.0
        total_value = None
        decisions: list[dict] = []
        blocked: list[dict] = []
        broker_order_ids: list[str] = []
        self._update_runtime(running=True, phase="market_check", last_error=None)

        try:
            with self._connection() as conn:
                control = repository.get_kis_paper_control(conn)
                if not control["enabled"]:
                    status = "disabled"
                elif not market_open:
                    status = "market_closed"
                elif not self.client.status()["order_enabled"]:
                    status = "order_locked"
                    error = "KIS paper order is disabled"
                elif not is_configured():
                    status = "model_unavailable"
                    error = "AI model is not configured"
                else:
                    self._update_runtime(phase="balance")
                    balance = self.client.get_balance()
                    risk = self._build_risk(conn, balance)
                    total_value = risk["total_value"]
                    broker_orders = self.client.get_daily_orders()
                    for broker_order in broker_orders:
                        repository.reconcile_kis_paper_order(conn, broker_order)
                    open_orders = [
                        order for order in broker_orders
                        if order["remaining_quantity"] > 0
                        and order["status"] in {"pending", "partial"}
                    ]
                    blocked = [
                        {
                            "code": order["code"],
                            "action": order["side"],
                            "rule": "open_broker_order",
                            "reason": (
                                f"KIS 주문 {order['broker_order_id']} 미체결 "
                                f"{order['remaining_quantity']}주 대기, 해당 종목만 제외"
                            ),
                        }
                        for order in open_orders
                    ]
                    open_order_codes = {order["code"] for order in open_orders}
                    self._update_runtime(phase="analysis")
                    self._refresh_completed_market_data(conn)
                    candidates = self._rank_candidates(conn)
                    if self._competition_enabled():
                        daily_return_pct = self._daily_return_pct(conn, risk["total_value"])
                        market_regime = competition_market_regime(
                            repository.get_market_breadth(conn),
                            risk["max_drawdown_pct"],
                            float(os.getenv("KIS_COMPETITION_MAX_DRAWDOWN_STOP_PCT", "8")),
                        )
                        target_exposure_pct = competition_target_exposure_pct(
                            market_regime,
                            risk["max_drawdown_pct"],
                            daily_return_pct,
                            float(os.getenv("KIS_COMPETITION_DAILY_STOP_PCT", "2.5")),
                            float(os.getenv("KIS_COMPETITION_MAX_DRAWDOWN_STOP_PCT", "8")),
                        )
                    else:
                        market_regime = AutonomousTradingEngine._market_regime(candidates)
                        target_exposure_pct = AutonomousTradingEngine._target_exposure_pct(
                            market_regime,
                            risk,
                        )
                    prompt = self._build_prompt(
                        risk,
                        candidates,
                        market_regime,
                        target_exposure_pct,
                    )
                    raw = ask_local_model(_SYSTEM_PROMPT, prompt)
                    proposed = (extract_json_block(raw) or {}).get("decisions") or []
                    allocation_risk = dict(risk)
                    allocation_risk["cash"] = self._realtime_orderable_cash(candidates)
                    decisions, guard_blocked = self._guard_decisions(
                        conn,
                        allocation_risk,
                        candidates,
                        proposed,
                        market_regime,
                        target_exposure_pct,
                        open_order_codes=open_order_codes,
                    )
                    blocked.extend(guard_blocked)
                    self._update_runtime(phase="execution")
                    broker_order_ids = self._execute(conn, decisions)
                    status = (
                        "executed" if broker_order_ids
                        else "pending_orders" if open_orders
                        else "observed"
                    )
                    repository.insert_kis_paper_snapshot(
                        conn,
                        total_value=risk["total_value"],
                        cash=risk["cash"],
                        evaluated_value=risk["evaluated_value"],
                        pnl=risk["total_value"] - risk["initial_capital"],
                    )

                repository.insert_kis_paper_cycle(
                    conn,
                    started_at=started_at,
                    status=status,
                    market_open=market_open,
                    market_regime=market_regime,
                    target_exposure_pct=target_exposure_pct,
                    decisions=decisions,
                    blocked_decisions=blocked,
                    broker_order_ids=broker_order_ids,
                    total_value=total_value,
                    error=error,
                )
        except Exception as exc:
            status = "error"
            error = str(exc)
            with self._connection() as conn:
                repository.insert_kis_paper_cycle(
                    conn,
                    started_at=started_at,
                    status=status,
                    market_open=market_open,
                    market_regime=market_regime,
                    target_exposure_pct=target_exposure_pct,
                    decisions=decisions,
                    blocked_decisions=blocked,
                    broker_order_ids=broker_order_ids,
                    total_value=total_value,
                    error=error,
                )
        finally:
            completed_at = datetime.now(timezone.utc).isoformat()
            self._update_runtime(
                running=False,
                phase=status,
                last_cycle_at=completed_at,
                last_error=error,
            )
            try:
                with self._connection() as conn:
                    repository.release_kis_paper_lease(conn, self._owner_id)
            finally:
                self._cycle_lock.release()

        return {
            "status": status,
            "market_open": market_open,
            "market_regime": market_regime,
            "target_exposure_pct": target_exposure_pct,
            "decisions": decisions,
            "blocked_decisions": blocked,
            "broker_order_ids": broker_order_ids,
            "total_value": total_value,
            "error": error,
        }

    def _run_loop(self) -> None:
        self._update_runtime(phase="idle")
        delay = max(0, int(os.getenv("KIS_PAPER_AUTONOMOUS_STARTUP_DELAY_SECONDS", "30")))
        if self._stop.wait(delay):
            return
        while not self._stop.is_set():
            try:
                with self._connection() as conn:
                    enabled = repository.get_kis_paper_control(conn)["enabled"]
                if enabled:
                    self.run_cycle()
            except Exception as exc:
                self._update_runtime(phase="error", last_error=str(exc))
            if self._stop.is_set():
                break
            self._wake.clear()
            self._wake.wait(self.interval_seconds)

    def _build_risk(self, conn, balance: dict) -> dict:
        total_value = float(balance.get("total_value") or 0)
        cash = float(balance.get("cash") or 0)
        evaluated = float(balance.get("evaluated_value") or 0)
        snapshots = repository.get_kis_paper_snapshots(conn)
        initial_capital = (
            float(snapshots[0]["total_value"])
            if snapshots
            else total_value
        )
        values = [float(item["total_value"]) for item in snapshots] + [total_value]
        peak = 0.0
        max_drawdown = 0.0
        for value in values:
            peak = max(peak, value)
            if peak:
                max_drawdown = min(max_drawdown, (value - peak) / peak * 100)
        positions = []
        for item in balance.get("positions") or []:
            positions.append({
                "code": item["code"],
                "name": item.get("name") or item["code"],
                "quantity": int(item["quantity"]),
                "avg_price": float(item.get("avg_price") or 0),
                "current_price": float(item.get("current_price") or 0),
                "market_value": float(item.get("market_value") or 0),
                "return_pct": float(item.get("return_pct") or 0),
            })
        return {
            "initial_capital": initial_capital,
            "total_value": total_value,
            "cash": cash,
            "evaluated_value": evaluated,
            "total_return_pct": (
                (total_value - initial_capital) / initial_capital * 100
                if initial_capital else 0
            ),
            "max_drawdown_pct": max_drawdown,
            "positions": positions,
        }

    def _rank_candidates(self, conn) -> list[dict]:
        pool_size = max(12, int(os.getenv("KIS_PAPER_CANDIDATE_POOL_SIZE", "30")))
        excluded_codes = self._excluded_candidate_codes(conn)
        if self._competition_enabled():
            universe_size = max(
                pool_size,
                int(os.getenv("KIS_COMPETITION_UNIVERSE_SIZE", "200")),
            )
            candidates = repository.get_candidates(
                conn,
                top_change=universe_size,
                top_volume=universe_size,
            )
            items = [
                (candidate, repository.get_price_history(conn, candidate["code"]))
                for candidate in candidates
                if candidate["code"] not in excluded_codes
            ]
            return rank_competition_candidates(
                items,
                pool_size=pool_size,
                min_avg_trading_value=float(
                    os.getenv("KIS_COMPETITION_MIN_AVG_TRADING_VALUE", "1000000000")
                ),
                min_price=float(os.getenv("KIS_COMPETITION_MIN_PRICE", "1000")),
                max_return_20_pct=float(
                    os.getenv("KIS_COMPETITION_MAX_20D_RETURN_PCT", "120")
                ),
                max_volatility_pct=float(
                    os.getenv("KIS_COMPETITION_MAX_VOLATILITY_PCT", "120")
                ),
            )
        ranked = []
        for candidate in repository.get_candidates(
            conn,
            top_change=max(30, pool_size),
            top_volume=max(20, pool_size),
        ):
            if candidate["code"] in excluded_codes:
                continue
            analytics = calculate_stock_analytics(
                repository.get_price_history(conn, candidate["code"])
            )
            score = analytics["technical_bias"]["score"]
            if abs(score) < 25:
                continue
            ranked.append({
                **candidate,
                "score": score,
                "rsi14": analytics["momentum"]["rsi14"],
                "macd_histogram": analytics["momentum"]["macd_histogram"],
            })
        ranked.sort(key=lambda item: abs(item["score"]), reverse=True)
        return ranked[:pool_size]

    @staticmethod
    def _excluded_candidate_codes(conn) -> set[str]:
        excluded = {
            code.strip()
            for code in os.getenv("KIS_PAPER_EXCLUDED_CODES", "").split(",")
            if code.strip()
        }
        lookback = max(
            0,
            int(os.getenv("KIS_PAPER_REJECTED_SYMBOL_LOOKBACK", "50")),
        )
        if lookback == 0:
            return excluded
        rejection_markers = (
            "40070000",
            "매매불가 종목",
            "매매불가종목",
            "not tradable",
        )
        for cycle in repository.get_kis_paper_cycles(conn, lookback):
            for decision in cycle.get("decisions") or []:
                error = str(decision.get("execution_error") or "").lower()
                if error and any(marker in error for marker in rejection_markers):
                    code = str(decision.get("code") or "").strip()
                    if code:
                        excluded.add(code)
        return excluded

    @staticmethod
    def _build_prompt(
        risk: dict,
        candidates: list[dict],
        market_regime: str,
        target_exposure_pct: float,
    ) -> str:
        positions = ", ".join(
            f"{item['name']}({item['code']}) {item['quantity']}주 수익률 {item['return_pct']:.2f}%"
            for item in risk["positions"]
        ) or "없음"
        candidate_lines = [
            (
                f"{item['name']}({item['code']}) 대회점수 {item['score']} "
                f"5일 {item.get('return_5_pct', 0):.2f}% "
                f"20일 {item.get('return_20_pct', 0):.2f}% "
                f"변동성 {item.get('volatility_pct', 0):.2f}%"
                if "return_20_pct" in item
                else f"{item['name']}({item['code']}) 기술점수 {item['score']} RSI {item.get('rsi14')}"
            )
            for item in candidates
        ]
        return (
            f"KIS 모의계좌 총자산 {risk['total_value']:.0f}원, 현금 {risk['cash']:.0f}원, "
            f"수익률 {risk['total_return_pct']:.2f}%, 최대낙폭 {risk['max_drawdown_pct']:.2f}%\n"
            f"시장국면 {market_regime}, 목표 투자비중 {target_exposure_pct:.1f}%\n"
            f"보유종목: {positions}\n후보:\n" + "\n".join(candidate_lines)
        )

    def _guard_decisions(
        self,
        conn,
        risk: dict,
        candidates: list[dict],
        proposed: list[dict],
        market_regime: str,
        target_exposure_pct: float,
        open_order_codes: set[str] | None = None,
    ) -> tuple[list[dict], list[dict]]:
        open_order_codes = open_order_codes or set()
        positions = {item["code"]: item for item in risk["positions"]}
        by_code = {item["code"]: item for item in candidates}
        max_orders = max(1, int(os.getenv("KIS_PAPER_MAX_ORDERS_PER_CYCLE", "5")))
        competition_mode = self._competition_enabled()
        max_position_pct = float(os.getenv(
            "KIS_COMPETITION_MAX_POSITION_PCT" if competition_mode else "KIS_PAPER_MAX_POSITION_PCT",
            "12" if competition_mode else "20",
        ))
        cash_reserve_pct = max(0.0, float(os.getenv("KIS_PAPER_CASH_RESERVE_PCT", "0")))
        stop_loss_pct = float(os.getenv("KIS_PAPER_STOP_LOSS_PCT", "5"))
        take_profit_pct = float(os.getenv("KIS_PAPER_TAKE_PROFIT_PCT", "12"))
        rotation_sell_score = float(os.getenv("KIS_PAPER_ROTATION_SELL_SCORE", "-1000"))
        cooldown_minutes = max(0, int(os.getenv("KIS_PAPER_COOLDOWN_MINUTES", "60")))
        max_positions = max(1, int(os.getenv("KIS_COMPETITION_MAX_POSITIONS", "10")))
        decisions: list[dict] = []
        blocked: list[dict] = []

        def block(code, action, rule, reason):
            blocked.append({"code": code, "action": action, "rule": rule, "reason": reason})

        target_invested = risk["total_value"] * target_exposure_pct / 100
        projected_evaluated = risk["evaluated_value"]
        if competition_mode and projected_evaluated > target_invested:
            excess = projected_evaluated - target_invested
            weakest = sorted(
                positions.values(),
                key=lambda position: by_code.get(position["code"], {}).get("score", -1),
            )
            for position in weakest:
                if excess <= 0 or len(decisions) >= max_orders:
                    break
                if position["code"] in open_order_codes:
                    continue
                price = float(position.get("current_price") or 0)
                if price <= 0:
                    continue
                quantity = min(position["quantity"], max(1, math.ceil(excess / price)))
                decisions.append({
                    "code": position["code"],
                    "action": "sell",
                    "quantity": quantity,
                    "reason": f"대회 모드 목표 투자비중 {target_exposure_pct:.0f}%로 위험 축소",
                })
                reduced = min(position["market_value"], quantity * price)
                excess -= reduced
                projected_evaluated -= reduced

        decided_codes = {item["code"] for item in decisions}
        for position in positions.values():
            if position["code"] in open_order_codes:
                continue
            if position["code"] in decided_codes:
                continue
            competition_exit = (
                self._competition_exit_reason(conn, position)
                if competition_mode else None
            )
            if competition_exit:
                decisions.append({
                    "code": position["code"],
                    "action": "sell",
                    "quantity": position["quantity"],
                    "reason": competition_exit,
                })
            elif not competition_mode and position["return_pct"] <= -stop_loss_pct:
                decisions.append({
                    "code": position["code"],
                    "action": "sell",
                    "quantity": position["quantity"],
                    "reason": f"손절 기준 {-stop_loss_pct:.1f}% 도달",
                })
            elif not competition_mode and position["return_pct"] >= take_profit_pct:
                decisions.append({
                    "code": position["code"],
                    "action": "sell",
                    "quantity": max(1, position["quantity"] // 2),
                    "reason": f"수익 보호 기준 {take_profit_pct:.1f}% 도달",
                })
            elif not competition_mode:
                score = self._position_score(conn, by_code, position["code"])
                if score is not None and score <= rotation_sell_score:
                    decisions.append({
                        "code": position["code"],
                        "action": "sell",
                        "quantity": position["quantity"],
                        "reason": f"기술 전망 약화(점수 {score:.0f})로 선제 로테이션 매도",
                    })

        proposed_buys = [item for item in proposed if item.get("action") == "buy"]
        if not competition_mode and market_regime == "bearish":
            for item in proposed_buys or [{"code": None}]:
                block(item.get("code"), "buy", "bearish_regime", "하락장 신규 매수 중단")
            return decisions[:max_orders], blocked

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
        cooldown_codes = {
            item["code"]
            for item in repository.get_kis_paper_orders(conn, 200)
            if datetime.fromisoformat(item["submitted_at"]) >= cutoff
        }
        proposed_reasons = {
            str(item.get("code")): str(item.get("reason") or "AI 추세 확인")
            for item in proposed_buys
        }
        ranked_codes = [item["code"] for item in candidates if item["score"] >= 25]
        ordered_codes = (
            ranked_codes + [code for code in proposed_reasons if code not in ranked_codes]
            if competition_mode
            else list(proposed_reasons) + [
                code for code in ranked_codes if code not in proposed_reasons
            ]
        )
        spendable_cash = max(0.0, risk["cash"] - risk["total_value"] * cash_reserve_pct / 100)
        remaining_cash = min(
            spendable_cash,
            max(0.0, target_invested - risk["evaluated_value"]),
        )
        projected_position_codes = set(positions) - {
            item["code"] for item in decisions
            if item["action"] == "sell"
            and item["quantity"] >= positions[item["code"]]["quantity"]
        }
        for code in ordered_codes:
            if len(decisions) >= max_orders:
                block(code, "buy", "cycle_order_limit", "사이클 주문 수 한도")
                continue
            if code in cooldown_codes:
                block(code, "buy", "cooldown", "최근 KIS 주문 재주문 대기")
                continue
            if code in open_order_codes:
                block(code, "buy", "open_broker_order", "동일 종목 미체결 주문 대기")
                continue
            if competition_mode and code not in projected_position_codes and len(projected_position_codes) >= max_positions:
                block(code, "buy", "max_positions", f"대회 모드 최대 {max_positions}종목")
                continue
            candidate = by_code.get(code)
            if not candidate or candidate["score"] < 25:
                block(code, "buy", "weak_signal", "기술점수 기준 미달")
                continue
            if candidate.get("change_pct") is not None and candidate["change_pct"] >= 15:
                block(code, "buy", "price_spike", "15% 이상 급등 추격 제한")
                continue
            existing_value = positions.get(code, {}).get("market_value", 0)
            position_limit_pct = (
                min(
                    max_position_pct,
                    position_target_pct(
                        candidate.get("volatility_pct"),
                        float(os.getenv("KIS_COMPETITION_BASE_POSITION_PCT", "12")),
                    ),
                )
                if competition_mode else max_position_pct
            )
            capacity = risk["total_value"] * position_limit_pct / 100 - existing_value
            if capacity <= 0:
                block(code, "buy", "position_limit", "종목당 비중 한도")
                continue
            try:
                price = float(self.provider.get_latest_price(code))
            except Exception:
                block(code, "buy", "quote_unavailable", "현재가 조회 실패")
                continue
            allocation = min(remaining_cash, capacity)
            quantity = int(allocation // price) if price > 0 else 0
            volume_cap = self._volume_cap(conn, code)
            if volume_cap is not None:
                quantity = min(quantity, volume_cap)
            if quantity <= 0:
                block(code, "buy", "insufficient_budget", "목표 비중 내 예산 부족")
                continue
            decisions.append({
                "code": code,
                "action": "buy",
                "quantity": quantity,
                "reason": proposed_reasons.get(code, "정량 상위 후보 분산 매수"),
            })
            projected_position_codes.add(code)
            remaining_cash -= quantity * price
        return decisions[:max_orders], blocked

    @staticmethod
    def _competition_enabled() -> bool:
        return os.getenv("KIS_PAPER_STRATEGY_MODE", "standard") == "competition_3m"

    def _competition_exit_reason(self, conn, position: dict) -> str | None:
        hard_stop_pct = float(os.getenv("KIS_COMPETITION_HARD_STOP_PCT", "6"))
        if position["return_pct"] <= -hard_stop_pct:
            return f"대회 모드 손실 제한 {-hard_stop_pct:.1f}% 도달"
        history = repository.get_price_history(conn, position["code"])
        if len(history) < 21:
            return None
        analytics = calculate_stock_analytics(history)
        ma20 = analytics["moving_averages"]["ma20"]
        atr14 = analytics["volatility"]["atr14"]
        current = float(position.get("current_price") or 0)
        closes = [float(bar["close"]) for bar in history]
        return_5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
        if ma20 and current < ma20 and return_5 < 0:
            return "20일 추세 이탈과 단기 모멘텀 약화"
        if atr14 and position["return_pct"] >= 3:
            peak = max(float(bar["high"]) for bar in history[-20:])
            trail_atr = float(os.getenv("KIS_COMPETITION_TRAILING_STOP_ATR", "2.5"))
            if current <= peak - atr14 * trail_atr:
                return f"최고가 대비 {trail_atr:.1f} ATR 추적손절"
        return None

    @staticmethod
    def _daily_return_pct(conn, current_total: float) -> float | None:
        kst = ZoneInfo("Asia/Seoul")
        today = datetime.now(kst).date()
        snapshots = [
            item for item in repository.get_kis_paper_snapshots(conn)
            if datetime.fromisoformat(item["ts"]).astimezone(kst).date() == today
        ]
        if not snapshots or not snapshots[0]["total_value"]:
            return None
        return (current_total / float(snapshots[0]["total_value"]) - 1) * 100

    @staticmethod
    def _position_score(conn, by_code: dict, code: str) -> float | None:
        candidate = by_code.get(code)
        if candidate is not None:
            return candidate["score"]
        history = repository.get_price_history(conn, code)
        if not history:
            return None
        return calculate_stock_analytics(history)["technical_bias"]["score"]

    @staticmethod
    def _volume_cap(conn, code: str) -> int | None:
        participation_pct = float(os.getenv("KIS_PAPER_MAX_VOLUME_PARTICIPATION_PCT", "0"))
        if participation_pct <= 0:
            return None
        avg_volume = repository.get_average_volume(conn, code)
        if not avg_volume:
            return None
        cap = int(avg_volume * participation_pct / 100)
        return cap if cap > 0 else None

    def _execute(self, conn, decisions: list[dict]) -> list[str]:
        executor = KisPaperExecutor(self.client, conn)
        broker_order_ids = []
        for index, decision in enumerate(decisions):
            if index:
                time.sleep(0.6)
            quantity = int(decision["quantity"])
            if decision["action"] == "buy":
                quantity = self._cap_to_realtime_buying_power(decision["code"], quantity)
                if quantity <= 0:
                    decision["execution_error"] = "실시간 주문가능금액 부족"
                    continue
            try:
                result = executor.place_order(
                    decision["code"],
                    decision["action"],
                    quantity,
                    reason=decision["reason"],
                )
                if result.broker_order_id:
                    broker_order_ids.append(result.broker_order_id)
            except OrderExecutionError as exc:
                decision["execution_error"] = str(exc)
        return broker_order_ids

    def _cap_to_realtime_buying_power(self, code: str, quantity: int) -> int:
        try:
            price = float(self.provider.get_latest_price(code))
            if price <= 0:
                return 0
            power = self.client.get_buying_power(code, price)
            max_affordable = int(power["orderable_cash"] // price)
        except (KisApiError, ValueError, ZeroDivisionError, KeyError):
            return 0
        return max(0, min(quantity, max_affordable))

    def _realtime_orderable_cash(self, candidates: list[dict]) -> float:
        for candidate in candidates:
            code = candidate.get("code")
            if not code:
                continue
            try:
                price = float(self.provider.get_latest_price(code))
                if price <= 0:
                    continue
                power = self.client.get_buying_power(code, price)
                return max(0.0, float(power.get("orderable_cash") or 0))
            except (KisApiError, ValueError, TypeError, KeyError):
                continue
        return 0.0

    def _connection(self):
        conn = sqlite3.connect(self.db_path)
        repository.init_db(conn)
        return conn

    def _refresh_completed_market_data(self, conn) -> None:
        if not self._competition_enabled() or not hasattr(self.provider, "get_market_snapshot"):
            return
        kst = ZoneInfo("Asia/Seoul")
        target = datetime.now(kst).date() - timedelta(days=1)
        if self._last_market_data_refresh_date == target.isoformat():
            return
        for offset in range(7):
            session_date = target - timedelta(days=offset)
            try:
                bars = self.provider.get_market_snapshot(session_date.strftime("%Y%m%d"))
            except Exception:
                continue
            if not bars:
                continue
            repository.upsert_market_snapshot(conn, bars)
            as_of = next(iter(bars.values())).date
            self._last_market_data_refresh_date = target.isoformat()
            self._update_runtime(market_data_as_of=as_of)
            return

    def _update_runtime(self, **values) -> None:
        with self._state_lock:
            self._runtime.update(values)
