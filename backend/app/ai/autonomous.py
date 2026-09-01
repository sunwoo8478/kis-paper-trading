import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import repository
from ..analytics import calculate_stock_analytics
from ..api.analytics import build_portfolio_risk
from ..execution.base import OrderExecutionError
from ..execution.simulated_executor import SimulatedExecutor
from .local_model import ask_local_model, extract_json_block, is_configured

_KST = ZoneInfo("Asia/Seoul")
_AUTONOMOUS_SYSTEM_PROMPT = (
    "너는 한국 주식 모의투자 계좌의 자율 운용 판단 모듈이다. "
    "제공된 후보와 기술지표 안에서만 판단하고 종목이나 가격을 추측하지 마라. "
    "수익 극대화보다 최대 낙폭 통제와 손실 제한을 우선한다. "
    "응답 마지막에 반드시 다음 JSON만 포함한다: "
    '```json\n{"decisions":[{"code":"종목코드","action":"buy|sell","reason":"근거"}]}\n```'
)


def is_regular_market_open(now: datetime | None = None) -> bool:
    current = (now or datetime.now(_KST)).astimezone(_KST)
    if current.weekday() >= 5:
        return False
    return time(9, 0) <= current.time().replace(tzinfo=None) <= time(15, 30)


class AutonomousTradingEngine:
    def __init__(self, db_path: str, provider):
        self.db_path = db_path
        self.provider = provider
        self.interval_seconds = max(30, int(os.getenv("AI_AUTONOMOUS_INTERVAL_SECONDS", "300")))
        self._stop = threading.Event()
        self._owner_id = str(uuid.uuid4())
        self._wake = threading.Event()
        self._cycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._runtime = {
            "running": False,
            "phase": "starting",
            "last_cycle_at": None,
            "last_error": None,
        }
        with self._connection() as conn:
            default_enabled = os.getenv("AI_AUTONOMOUS_ENABLED", "false").lower() in {"1", "true", "yes"}
            repository.ensure_autonomous_control(conn, default_enabled)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="autonomous-trading", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def set_enabled(self, enabled: bool) -> None:
        with self._connection() as conn:
            repository.set_autonomous_enabled(conn, enabled)
        self._wake.set()

    def trigger(self) -> dict:
        return self.run_cycle()

    def begin_experiment(
        self,
        name: str,
        initial_capital: float,
        benchmark_symbol: str | None = None,
        benchmark_start_value: float | None = None,
    ) -> dict:
        with self._cycle_lock:
            with self._connection() as conn:
                return repository.start_paper_experiment(
                    conn,
                    name=name,
                    initial_capital=initial_capital,
                    strategy_version=os.getenv("AI_STRATEGY_VERSION", "autonomous-v2"),
                    benchmark_symbol=benchmark_symbol,
                    benchmark_start_value=benchmark_start_value,
                )

    def status(self) -> dict:
        with self._connection() as conn:
            control = repository.get_autonomous_control(conn)
            cycles = repository.get_autonomous_cycles(conn, limit=1)
        with self._state_lock:
            runtime = dict(self._runtime)
        next_cycle = None
        if control["enabled"] and runtime["last_cycle_at"]:
            last = datetime.fromisoformat(runtime["last_cycle_at"])
            next_cycle = (last + timedelta(seconds=self.interval_seconds)).isoformat()
        return {
            **runtime,
            **control,
            "execution_mode": "paper",
            "market_open": self._market_open(),
            "interval_seconds": self.interval_seconds,
            "next_cycle_at": next_cycle,
            "latest_cycle": cycles[0] if cycles else None,
        }

    def run_cycle(self, now: datetime | None = None) -> dict:
        if not self._cycle_lock.acquire(blocking=False):
            return {"status": "already_running"}

        lease_acquired = False
        with self._connection() as conn:
            lease_acquired = repository.acquire_autonomous_lease(
                conn, self._owner_id, max(self.interval_seconds, 120)
            )
        if not lease_acquired:
            self._cycle_lock.release()
            return {"status": "lease_held", "order_ids": []}

        started_at = datetime.now(timezone.utc).isoformat()
        market_open = self._market_open(now)
        decisions: list[dict] = []
        blocked_decisions: list[dict] = []
        order_ids: list[int] = []
        total_value = None
        market_regime = "market_closed" if not market_open else "unavailable"
        target_exposure_pct = 0.0
        status = "market_closed"
        error = None
        self._update_runtime(running=True, phase="market_check", last_error=None)

        try:
            with self._connection() as conn:
                control = repository.get_autonomous_control(conn)
                if not control["enabled"]:
                    status = "disabled"
                elif not market_open:
                    status = "market_closed"
                elif not is_configured():
                    status = "model_unavailable"
                    error = "AI model is not configured"
                else:
                    self._update_runtime(phase="analysis")
                    risk = build_portfolio_risk(conn, self.provider)
                    total_value = risk["total_value"]
                    candidates = self._rank_candidates(conn)
                    market_regime = self._market_regime(candidates, risk)
                    target_exposure_pct = self._target_exposure_pct(market_regime, risk)
                    prompt = self._build_prompt(risk, candidates, market_regime)
                    raw = ask_local_model(_AUTONOMOUS_SYSTEM_PROMPT, prompt)
                    proposed = (extract_json_block(raw) or {}).get("decisions") or []
                    decisions, blocked_decisions = self._guard_decisions(
                        conn,
                        risk,
                        candidates,
                        proposed,
                        market_regime,
                        target_exposure_pct,
                    )
                    self._update_runtime(phase="execution")
                    order_ids = self._execute(conn, decisions)
                    status = "executed" if order_ids else "observed"

                    refreshed = build_portfolio_risk(conn, self.provider)
                    total_value = refreshed["total_value"]
                    repository.insert_snapshot(
                        conn,
                        refreshed["total_value"],
                        refreshed["cash"],
                        refreshed["evaluated_value"],
                        refreshed["total_value"] - refreshed["initial_capital"],
                    )
                    repository.insert_agent_run(
                        conn,
                        candidates=json.dumps([item["code"] for item in candidates], ensure_ascii=False),
                        decisions=json.dumps(decisions, ensure_ascii=False),
                        reasoning="[자율운용] " + (raw.split("```json")[0].strip() or "정량 필터 기반 판단"),
                        order_ids=json.dumps(order_ids),
                    )

                repository.insert_autonomous_cycle(
                    conn,
                    started_at=started_at,
                    status=status,
                    market_open=market_open,
                    decisions=json.dumps(decisions, ensure_ascii=False),
                    order_ids=json.dumps(order_ids),
                    total_value=total_value,
                    error=error,
                    market_regime=market_regime,
                    target_exposure_pct=target_exposure_pct,
                    blocked_decisions=json.dumps(blocked_decisions, ensure_ascii=False),
                )
        except Exception as exc:
            status = "error"
            error = str(exc)
            with self._connection() as conn:
                repository.insert_autonomous_cycle(
                    conn,
                    started_at=started_at,
                    status=status,
                    market_open=market_open,
                    decisions=json.dumps(decisions, ensure_ascii=False),
                    order_ids=json.dumps(order_ids),
                    total_value=total_value,
                    error=error,
                    market_regime=market_regime,
                    target_exposure_pct=target_exposure_pct,
                    blocked_decisions=json.dumps(blocked_decisions, ensure_ascii=False),
                )
        finally:
            finished_at = datetime.now(timezone.utc).isoformat()
            self._update_runtime(
                running=False,
                phase=status,
                last_cycle_at=finished_at,
                last_error=error,
            )
            try:
                with self._connection() as conn:
                    repository.release_autonomous_lease(conn, self._owner_id)
            finally:
                self._cycle_lock.release()

        return {
            "status": status,
            "market_open": market_open,
            "decisions": decisions,
            "blocked_decisions": blocked_decisions,
            "order_ids": order_ids,
            "total_value": total_value,
            "market_regime": market_regime,
            "target_exposure_pct": target_exposure_pct,
            "error": error,
        }

    def _run_loop(self) -> None:
        self._update_runtime(phase="idle")
        startup_delay = max(0, int(os.getenv("AI_AUTONOMOUS_STARTUP_DELAY_SECONDS", "10")))
        if self._stop.wait(startup_delay):
            return
        while not self._stop.is_set():
            try:
                with self._connection() as conn:
                    enabled = repository.get_autonomous_control(conn)["enabled"]
                if enabled:
                    self.run_cycle()
            except Exception as exc:
                self._update_runtime(last_error=str(exc), phase="error")
            if self._stop.is_set():
                break
            self._wake.clear()
            self._wake.wait(self.interval_seconds)

    def _market_open(self, now: datetime | None = None) -> bool:
        if not is_regular_market_open(now):
            return False
        if now is not None or not hasattr(self.provider, "get_market_status"):
            return True
        try:
            return self.provider.get_market_status() == "OPEN"
        except Exception:
            return False

    def _rank_candidates(self, conn) -> list[dict]:
        raw_candidates = repository.get_candidates(conn)
        histories = {
            candidate["code"]: repository.get_price_history(conn, candidate["code"])
            for candidate in raw_candidates
        }
        latest_dates = [history[-1]["date"] for history in histories.values() if history]
        if not latest_dates:
            return []
        freshest_date = max(latest_dates)
        stale_days = int(os.getenv("AI_CANDIDATE_STALE_DAYS", "9999"))
        min_avg_trading_value = float(os.getenv("AI_CANDIDATE_MIN_AVG_TRADING_VALUE", "0"))

        ranked = []
        for candidate in raw_candidates:
            history = histories[candidate["code"]]
            if not history:
                continue
            if self._days_behind(history[-1]["date"], freshest_date) > stale_days:
                continue
            recent = history[-20:]
            avg_trading_value = sum(bar["close"] * bar["volume"] for bar in recent) / len(recent)
            if avg_trading_value < min_avg_trading_value:
                continue
            analytics = calculate_stock_analytics(history)
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
    def _days_behind(candidate_date: str, freshest_date: str) -> int:
        return (datetime.fromisoformat(freshest_date) - datetime.fromisoformat(candidate_date)).days

    @staticmethod
    def _position_score(conn, by_code: dict, code: str) -> float | None:
        candidate = by_code.get(code)
        if candidate is not None:
            return candidate["score"]
        history = repository.get_price_history(conn, code)
        if not history:
            return None
        return calculate_stock_analytics(history)["technical_bias"]["score"]

    def _build_prompt(self, risk: dict, candidates: list[dict], market_regime: str = "neutral") -> str:
        positions = ", ".join(
            f"{item['code']} {item['quantity']}주 수익률{item['return_pct']:.2f}%"
            for item in risk["positions"]
        ) or "없음"
        candidate_lines = [
            f"{item['code']} {item['name']} 기술점수{item['score']} "
            f"전일변동{self._format_number(item.get('change_pct'))}% RSI{self._format_number(item.get('rsi14'))}"
            for item in candidates
        ]
        return (
            f"총자산 {risk['total_value']:.0f}원, 현금 {risk['cash']:.0f}원, "
            f"누적수익률 {risk['total_return_pct']:.2f}%, 최대낙폭 {risk['max_drawdown_pct']:.2f}%\n"
            f"시장 국면 {market_regime}. structural_decline/recession_rebalance/bearish 국면에서는 신규 매수를 제안하지 마라.\n"
            "위험 한도를 지키면서 가용 현금을 전액 분산하도록 매수 후보를 충분히 선택하라.\n"
            f"보유종목: {positions}\n후보:\n" + "\n".join(candidate_lines)
        )

    def _guard_decisions(
        self,
        conn,
        risk: dict,
        candidates: list[dict],
        proposed: list[dict],
        market_regime: str = "neutral",
        target_exposure_pct: float | None = None,
    ) -> tuple[list[dict], list[dict]]:
        by_code = {item["code"]: item for item in candidates}
        positions = {item["code"]: item for item in risk["positions"]}
        max_orders = max(1, int(os.getenv("AI_AUTONOMOUS_MAX_ORDERS_PER_CYCLE", "10")))
        max_position_pct = float(os.getenv("AI_MAX_POSITION_PCT", "20"))
        cash_reserve_pct = max(0.0, float(os.getenv("AI_AUTONOMOUS_CASH_RESERVE_PCT", "0")))
        stop_loss_pct = float(os.getenv("AI_AUTONOMOUS_STOP_LOSS_PCT", "5"))
        take_profit_pct = float(os.getenv("AI_AUTONOMOUS_TAKE_PROFIT_PCT", "12"))
        rotation_sell_score = float(os.getenv("AI_AUTONOMOUS_ROTATION_SELL_SCORE", "-1000"))
        max_daily_loss_pct = float(os.getenv("AI_MAX_DAILY_LOSS_PCT", "3"))
        cooldown_minutes = max(0, int(os.getenv("AI_AUTONOMOUS_COOLDOWN_MINUTES", "60")))
        daily_loss_pct = self._daily_loss_pct(conn, risk["total_value"])
        buying_allowed = daily_loss_pct is None or daily_loss_pct > -max_daily_loss_pct
        cooldown_codes = self._cooldown_codes(conn, cooldown_minutes)
        guarded = []
        blocked = []

        def block(code: str | None, action: str, rule: str, reason: str) -> None:
            blocked.append({
                "code": code,
                "action": action,
                "rule": rule,
                "reason": reason,
            })

        for position in positions.values():
            if position["return_pct"] <= -stop_loss_pct:
                guarded.append({
                    "code": position["code"], "action": "sell", "quantity": position["quantity"],
                    "reason": f"손절 기준 {-stop_loss_pct:.1f}% 도달",
                })
            elif position["return_pct"] >= take_profit_pct:
                guarded.append({
                    "code": position["code"], "action": "sell",
                    "quantity": max(1, position["quantity"] // 2),
                    "reason": f"수익 보호 기준 {take_profit_pct:.1f}% 도달",
                })
            else:
                score = self._position_score(conn, by_code, position["code"])
                if score is not None and score <= rotation_sell_score:
                    guarded.append({
                        "code": position["code"], "action": "sell", "quantity": position["quantity"],
                        "reason": f"기술 전망 약화(점수 {score:.0f})로 선제 로테이션 매도",
                    })

        for item in proposed:
            if len(guarded) >= max_orders:
                break
            code = str(item.get("code") or "")
            action = item.get("action")
            candidate = by_code.get(code)
            if action == "sell" and code in positions:
                if any(decision["code"] == code for decision in guarded):
                    continue
                if candidate and candidate["score"] <= -25:
                    guarded.append({
                        "code": code, "action": "sell", "quantity": positions[code]["quantity"],
                        "reason": str(item.get("reason") or "기술 추세 약화"),
                    })
        proposed_buys = [item for item in proposed if item.get("action") == "buy"]
        if not buying_allowed:
            for item in proposed_buys or [{"code": None}]:
                block(
                    str(item.get("code") or "") or None,
                    "buy",
                    "daily_loss_limit",
                    f"일일 손실 한도 {-max_daily_loss_pct:.1f}% 도달로 신규 매수 중단",
                )
        blocked_regimes = {"structural_decline", "recession_rebalance", "bearish"}
        if market_regime in blocked_regimes:
            regime_label = {
                "structural_decline": "구조적 하락",
                "recession_rebalance": "침체 리밸런싱",
                "bearish": "하락장",
            }[market_regime]
            for item in proposed_buys or [{"code": None}]:
                block(
                    str(item.get("code") or "") or None,
                    "buy",
                    "bearish_regime",
                    f"{regime_label} 국면으로 분류되어 신규 매수 중단",
                )
        if len(guarded) >= max_orders:
            block(None, "buy", "cycle_order_limit", "사이클당 주문 수 한도 도달")
        if not buying_allowed or market_regime in blocked_regimes or len(guarded) >= max_orders:
            return guarded[:max_orders], blocked

        proposed_reasons = {
            str(item.get("code")): str(item.get("reason") or "AI 기술 추세 확인")
            for item in proposed
            if item.get("action") == "buy"
        }
        ordered_codes = list(proposed_reasons)
        ordered_codes.extend(
            item["code"] for item in candidates
            if item["score"] >= 25 and item["code"] not in proposed_reasons
        )
        buy_slots = max_orders - len(guarded)
        eligible = []
        for code in ordered_codes:
            if len(eligible) >= buy_slots:
                block(code, "buy", "cycle_order_limit", "사이클당 주문 후보 수 한도 도달")
                continue
            if code in cooldown_codes:
                block(code, "buy", "cooldown", "최근 체결 종목 재주문 대기시간 적용")
                continue
            candidate = by_code.get(code)
            if not candidate or candidate["score"] < 25:
                block(code, "buy", "weak_signal", "매수 기술점수 기준 25 미달")
                continue
            if candidate.get("change_pct") is not None and candidate["change_pct"] >= 15:
                block(code, "buy", "price_spike", "당일 급등률 15% 이상으로 추격 매수 제한")
                continue
            existing_value = positions.get(code, {}).get("market_value", 0)
            capacity = risk["total_value"] * max_position_pct / 100 - existing_value
            if capacity <= 0:
                block(code, "buy", "position_limit", "종목당 최대 비중 한도 도달")
                continue
            try:
                price = float(self.provider.get_latest_price(code))
            except Exception:
                block(code, "buy", "quote_unavailable", "현재가 조회 실패")
                continue
            if price <= 0:
                block(code, "buy", "invalid_quote", "유효하지 않은 현재가")
                continue
            eligible.append({
                "code": code,
                "price": price,
                "capacity": capacity,
                "reason": proposed_reasons.get(code, "가용현금 전액 분산을 위한 정량 상위 후보"),
            })

        target_exposure_pct = (
            self._target_exposure_pct(market_regime, risk)
            if target_exposure_pct is None
            else target_exposure_pct
        )
        target_invested_value = risk["total_value"] * target_exposure_pct / 100
        exposure_budget = max(0.0, target_invested_value - risk["evaluated_value"])
        spendable_cash = max(
            0.0,
            risk["cash"] - risk["total_value"] * cash_reserve_pct / 100,
        )
        remaining_cash = min(spendable_cash, exposure_budget)
        if remaining_cash <= 0 and eligible:
            block(
                None,
                "buy",
                "target_exposure_reached",
                f"현재 투자금이 {target_exposure_pct:.1f}% 목표 투자비중에 도달",
            )
        buy_cost_multiplier = 1 + (
            float(os.getenv("SIMULATED_SLIPPAGE_BPS", "0"))
            + float(os.getenv("SIMULATED_COMMISSION_BPS", "0"))
        ) / 10_000
        for item in eligible:
            if remaining_cash <= 0:
                break
            allocation = min(remaining_cash, item["capacity"])
            estimated_fill = item["price"] * buy_cost_multiplier
            quantity = int(allocation // estimated_fill)
            if quantity <= 0:
                block(item["code"], "buy", "insufficient_budget", "목표 비중 내 매수 가능 금액 부족")
                continue
            estimated_cost = quantity * estimated_fill
            remaining_cash -= estimated_cost
            guarded.append({
                "code": item["code"], "action": "buy", "quantity": quantity,
                "reason": item["reason"],
            })

        return guarded[:max_orders], blocked

    @staticmethod
    def _market_regime(candidates: list[dict], risk: dict | None = None) -> str:
        directional = [item["score"] for item in candidates if abs(item["score"]) >= 25]
        if not directional:
            return "neutral"
        bullish_ratio = sum(score > 0 for score in directional) / len(directional)
        if bullish_ratio >= 0.65:
            return "bullish"
        if bullish_ratio > 0.35:
            return "neutral"
        if risk is None:
            return "bearish"

        max_drawdown = float(risk.get("max_drawdown_pct") or 0)
        rsi_values = [
            item["rsi14"] for item in candidates
            if abs(item["score"]) >= 25 and item.get("rsi14") is not None
        ]
        avg_rsi = sum(rsi_values) / len(rsi_values) if rsi_values else 50.0

        if max_drawdown <= -15:
            return "recession_rebalance"
        if avg_rsi <= 30:
            return "oversold"
        if max_drawdown <= -7:
            return "structural_decline"
        return "correction"

    @staticmethod
    def _target_exposure_pct(market_regime: str, risk: dict) -> float:
        defaults = {
            "bullish": 100.0,
            "neutral": 80.0,
            "correction": 60.0,
            "oversold": 50.0,
            "structural_decline": 20.0,
            "recession_rebalance": 0.0,
            "bearish": 20.0,
        }
        env_names = {
            "bullish": "AI_BULLISH_TARGET_EXPOSURE_PCT",
            "neutral": "AI_NEUTRAL_TARGET_EXPOSURE_PCT",
            "correction": "AI_CORRECTION_TARGET_EXPOSURE_PCT",
            "oversold": "AI_OVERSOLD_TARGET_EXPOSURE_PCT",
            "structural_decline": "AI_STRUCTURAL_DECLINE_TARGET_EXPOSURE_PCT",
            "recession_rebalance": "AI_RECESSION_REBALANCE_TARGET_EXPOSURE_PCT",
            "bearish": "AI_BEARISH_TARGET_EXPOSURE_PCT",
        }
        target = float(os.getenv(env_names.get(market_regime, ""), defaults.get(market_regime, 0.0)))
        max_drawdown = float(risk.get("max_drawdown_pct") or 0)
        if max_drawdown <= -10:
            target = 0.0
        elif max_drawdown <= -7:
            target = min(target, 30.0)
        elif max_drawdown <= -5:
            target = min(target, 50.0)
        return max(0.0, min(target, 100.0))

    @staticmethod
    def _format_number(value) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "N/A"

    @staticmethod
    def _daily_loss_pct(conn, current_total: float) -> float | None:
        today = datetime.now(timezone.utc).date()
        experiment = repository.get_active_experiment(conn)
        snapshots = [
            item for item in repository.get_snapshots(
                conn, experiment["started_at"] if experiment else None
            )
            if datetime.fromisoformat(item["ts"]).date() == today
        ]
        if not snapshots or not snapshots[0]["total_value"]:
            return None
        opening_value = float(snapshots[0]["total_value"])
        return (current_total - opening_value) / opening_value * 100

    @staticmethod
    def _cooldown_codes(conn, cooldown_minutes: int) -> set[str]:
        if cooldown_minutes <= 0:
            return set()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
        experiment = repository.get_active_experiment(conn)
        codes = set()
        for order in repository.get_orders(
            conn, experiment["started_at"] if experiment else None
        ):
            if order["status"] != "filled" or not order["filled_at"]:
                continue
            filled_at = datetime.fromisoformat(order["filled_at"])
            if filled_at >= cutoff:
                codes.add(order["code"])
        return codes

    def _execute(self, conn, decisions: list[dict]) -> list[int]:
        executor = SimulatedExecutor(self.provider, conn)
        order_ids = []
        for decision in decisions:
            try:
                result = executor.place_order(
                    decision["code"], decision["action"], int(decision["quantity"])
                )
                order_ids.append(result.order_id)
            except (OrderExecutionError, ValueError):
                continue
        return order_ids

    def _connection(self):
        conn = sqlite3.connect(self.db_path)
        repository.init_db(conn)
        return conn

    def _update_runtime(self, **values) -> None:
        with self._state_lock:
            self._runtime.update(values)
