import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from .. import repository
from ..analytics import calculate_stock_analytics
from ..execution.base import OrderExecutionError
from ..execution.kis_paper_executor import KisPaperExecutor
from ..integrations.kis import KisApiError, KisPaperClient
from .autonomous import AutonomousTradingEngine, is_regular_market_open
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
        self._runtime = {
            "running": False,
            "phase": "starting",
            "last_cycle_at": None,
            "last_error": None,
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
                    if open_orders:
                        status = "pending_orders"
                        market_regime = "pending_orders"
                        target_exposure_pct = (
                            risk["evaluated_value"] / risk["total_value"] * 100
                            if risk["total_value"] else 0
                        )
                        blocked = [
                            {
                                "code": order["code"],
                                "action": order["side"],
                                "rule": "open_broker_order",
                                "reason": (
                                    f"KIS 주문 {order['broker_order_id']} 미체결 "
                                    f"{order['remaining_quantity']}주 대기"
                                ),
                            }
                            for order in open_orders
                        ]
                    else:
                        self._update_runtime(phase="analysis")
                        candidates = self._rank_candidates(conn)
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
                        decisions, blocked = self._guard_decisions(
                            conn,
                            risk,
                            candidates,
                            proposed,
                            market_regime,
                            target_exposure_pct,
                        )
                        self._update_runtime(phase="execution")
                        broker_order_ids = self._execute(conn, decisions)
                        status = "executed" if broker_order_ids else "observed"
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
        ranked = []
        for candidate in repository.get_candidates(conn):
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
        return ranked[:12]

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
            f"{item['name']}({item['code']}) 기술점수 {item['score']} RSI {item.get('rsi14')}"
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
    ) -> tuple[list[dict], list[dict]]:
        positions = {item["code"]: item for item in risk["positions"]}
        by_code = {item["code"]: item for item in candidates}
        max_orders = max(1, int(os.getenv("KIS_PAPER_MAX_ORDERS_PER_CYCLE", "5")))
        max_position_pct = float(os.getenv("KIS_PAPER_MAX_POSITION_PCT", "20"))
        cash_reserve_pct = max(0.0, float(os.getenv("KIS_PAPER_CASH_RESERVE_PCT", "0")))
        stop_loss_pct = float(os.getenv("KIS_PAPER_STOP_LOSS_PCT", "5"))
        take_profit_pct = float(os.getenv("KIS_PAPER_TAKE_PROFIT_PCT", "12"))
        rotation_sell_score = float(os.getenv("KIS_PAPER_ROTATION_SELL_SCORE", "-1000"))
        cooldown_minutes = max(0, int(os.getenv("KIS_PAPER_COOLDOWN_MINUTES", "60")))
        decisions: list[dict] = []
        blocked: list[dict] = []

        def block(code, action, rule, reason):
            blocked.append({"code": code, "action": action, "rule": rule, "reason": reason})

        for position in positions.values():
            if position["return_pct"] <= -stop_loss_pct:
                decisions.append({
                    "code": position["code"],
                    "action": "sell",
                    "quantity": position["quantity"],
                    "reason": f"손절 기준 {-stop_loss_pct:.1f}% 도달",
                })
            elif position["return_pct"] >= take_profit_pct:
                decisions.append({
                    "code": position["code"],
                    "action": "sell",
                    "quantity": max(1, position["quantity"] // 2),
                    "reason": f"수익 보호 기준 {take_profit_pct:.1f}% 도달",
                })
            else:
                score = self._position_score(conn, by_code, position["code"])
                if score is not None and score <= rotation_sell_score:
                    decisions.append({
                        "code": position["code"],
                        "action": "sell",
                        "quantity": position["quantity"],
                        "reason": f"기술 전망 약화(점수 {score:.0f})로 선제 로테이션 매도",
                    })

        proposed_buys = [item for item in proposed if item.get("action") == "buy"]
        if market_regime == "bearish":
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
        ordered_codes = list(proposed_reasons)
        ordered_codes.extend(
            item["code"] for item in candidates
            if item["score"] >= 25 and item["code"] not in proposed_reasons
        )
        target_invested = risk["total_value"] * target_exposure_pct / 100
        spendable_cash = max(0.0, risk["cash"] - risk["total_value"] * cash_reserve_pct / 100)
        remaining_cash = min(
            spendable_cash,
            max(0.0, target_invested - risk["evaluated_value"]),
        )
        for code in ordered_codes:
            if len(decisions) >= max_orders:
                block(code, "buy", "cycle_order_limit", "사이클 주문 수 한도")
                continue
            if code in cooldown_codes:
                block(code, "buy", "cooldown", "최근 KIS 주문 재주문 대기")
                continue
            candidate = by_code.get(code)
            if not candidate or candidate["score"] < 25:
                block(code, "buy", "weak_signal", "기술점수 기준 미달")
                continue
            if candidate.get("change_pct") is not None and candidate["change_pct"] >= 15:
                block(code, "buy", "price_spike", "15% 이상 급등 추격 제한")
                continue
            existing_value = positions.get(code, {}).get("market_value", 0)
            capacity = risk["total_value"] * max_position_pct / 100 - existing_value
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
            remaining_cash -= quantity * price
        return decisions[:max_orders], blocked

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

    def _connection(self):
        conn = sqlite3.connect(self.db_path)
        repository.init_db(conn)
        return conn

    def _update_runtime(self, **values) -> None:
        with self._state_lock:
            self._runtime.update(values)
