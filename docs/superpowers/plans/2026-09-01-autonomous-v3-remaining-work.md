# Autonomous v3 Remaining Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap between `docs/superpowers/specs/2026-08-31-autonomous-trading-v3.md` and the current codebase. Investigation found phase 1 of the spec (market-regime classification, target exposure, structured block reasons) is already implemented in `backend/app/ai/autonomous.py`. This plan covers the remaining gaps: liquidity/staleness candidate filtering, volume-capped partial-fill execution, multi-period backtest comparison with profit factor and turnover, and AI no-action explanation.

**Architecture:** Each gap is closed with a small, independently testable change inside the existing module it belongs to — no new files, no new abstractions. All new risk/liquidity thresholds are environment-variable gated with permissive defaults (matching the existing `SIMULATED_*_BPS` / `AI_AUTONOMOUS_*` convention) so existing tests and existing `.env` deployments are unaffected unless a value is explicitly set.

**Tech Stack:** FastAPI + SQLite backend (`backend/app/`), `uv run pytest` for tests.

## Global Constraints

- All order/account mutations flow only through `SimulatedExecutor` — never bypass it (spec: "모든 주문은 자율운용 엔진만 실행한다").
- New env vars default to a value that disables the new behavior, so no existing test needs modification: `AI_CANDIDATE_STALE_DAYS=9999`, `AI_CANDIDATE_MIN_AVG_TRADING_VALUE=0`, `SIMULATED_MAX_VOLUME_PARTICIPATION_PCT=0`.
- Never guess unrecorded facts in AI-facing text — the no-action explanation must be built only from `engine_status["latest_cycle"]` fields that already exist (`market_regime`, `target_exposure_pct`, `blocked_decisions`), per spec "기록에 없는 정보는 추측하지 않는다".
- Run `cd backend && uv run pytest -q` after every task; it must stay at 100% pass with only new tests added (currently 111 passed).
- Follow existing code style: no comments unless explaining a non-obvious constraint, `os.getenv(...)` read inline where used (not centralized config), Korean user-facing strings matching the existing tone.

---

### Task 1: Candidate liquidity and staleness filter

**Files:**
- Modify: `backend/app/ai/autonomous.py:270-285` (`_rank_candidates` method)
- Test: `backend/tests/test_autonomous.py`

**Interfaces:**
- Consumes: `repository.get_candidates(conn)` (existing, unchanged), `repository.get_price_history(conn, code)` (existing, unchanged) — each history item is `{"date": str, "open": float, "high": float, "low": float, "close": float, "volume": int}`.
- Produces: `_rank_candidates(conn) -> list[dict]` — same return shape as before (`code, name, market, ..., score, rsi14, macd_histogram`), just with two extra exclusion rules applied before scoring. No signature change, so no other task depends on new interface surface.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_autonomous.py`:

```python
def test_rank_candidates_excludes_stale_and_illiquid_codes(tmp_path, monkeypatch):
    from app.market_data.base import Stock

    db_path = str(tmp_path / "liquidity.db")
    conn = sqlite3.connect(db_path)
    repository.init_db(conn, 1_000_000)
    repository.upsert_stocks(conn, [
        Stock("000001", "정상종목", "KOSPI"),
        Stock("000002", "거래대금부족", "KOSPI"),
        Stock("000003", "데이터오래됨", "KOSPI"),
    ])
    fresh_bars = [
        OhlcvBar(
            date=f"2026-06-{index + 1:02d}", open=900 + index, high=920 + index,
            low=890 + index, close=900 + index * 2, volume=50_000 + index,
        )
        for index in range(30)
    ]
    thin_bars = [
        OhlcvBar(
            date=f"2026-06-{index + 1:02d}", open=900 + index, high=920 + index,
            low=890 + index, close=900 + index * 2, volume=10,
        )
        for index in range(30)
    ]
    stale_bars = fresh_bars[:-10]
    repository.upsert_price_history(conn, "000001", fresh_bars)
    repository.upsert_price_history(conn, "000002", thin_bars)
    repository.upsert_price_history(conn, "000003", stale_bars)
    conn.close()

    monkeypatch.setenv("AI_CANDIDATE_STALE_DAYS", "5")
    monkeypatch.setenv("AI_CANDIDATE_MIN_AVG_TRADING_VALUE", "1000000")
    engine = AutonomousTradingEngine(db_path, FixedPriceProvider())
    conn = sqlite3.connect(db_path)

    ranked = engine._rank_candidates(conn)

    codes = {item["code"] for item in ranked}
    assert "000001" in codes
    assert "000002" not in codes
    assert "000003" not in codes
    conn.close()


def test_rank_candidates_filter_disabled_by_default(tmp_path):
    db_path = str(tmp_path / "liquidity-default.db")
    _seed_uptrend(db_path)
    engine = AutonomousTradingEngine(db_path, FixedPriceProvider())
    conn = sqlite3.connect(db_path)

    ranked = engine._rank_candidates(conn)

    assert any(item["code"] == "005930" for item in ranked)
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_autonomous.py -k "rank_candidates" -v`
Expected: FAIL — `000002`/`000003` still present (no filter exists yet), or attribute errors if the test references something not yet returned.

- [ ] **Step 3: Implement the filter**

Replace `_rank_candidates` in `backend/app/ai/autonomous.py:270-285` with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_autonomous.py -v`
Expected: PASS, all tests including the two new ones and every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/autonomous.py backend/tests/test_autonomous.py
git commit -m "feat: filter autonomous candidates by staleness and trading value"
```

---

### Task 2: Volume-capped partial-fill execution

**Files:**
- Modify: `backend/app/repository.py` (add function near `get_price_history`, `backend/app/repository.py:1036`)
- Modify: `backend/app/execution/base.py:5-15` (`OrderResult`)
- Modify: `backend/app/execution/simulated_executor.py`
- Test: `backend/tests/test_repository.py`, `backend/tests/test_simulated_executor.py`

**Interfaces:**
- Consumes: `orders` table columns `requested_quantity`, `filled_quantity`, `fill_reason`, `status` (already exist per `record_order`/`fill_pending_order` in `backend/app/repository.py:440-529` — no schema migration needed).
- Produces: `repository.get_average_daily_volume(conn, code, days=20) -> float | None` (new); `OrderResult.filled_quantity: int | None = None` (new field, defaults to `None` meaning "same as quantity" for full fills — existing callers unaffected since it's optional with a default).

- [ ] **Step 1: Write the failing test for the repository helper**

Add to `backend/tests/test_repository.py`:

```python
def test_get_average_daily_volume_averages_recent_bars():
    conn = sqlite3.connect(":memory:")
    repository.init_db(conn)
    repository.upsert_stocks(conn, [Stock("005930", "삼성전자", "KOSPI")])
    bars = [
        OhlcvBar(date=f"2026-06-{i + 1:02d}", open=100, high=110, low=90, close=100, volume=1000 + i * 10)
        for i in range(30)
    ]
    repository.upsert_price_history(conn, "005930", bars)

    average = repository.get_average_daily_volume(conn, "005930", days=20)

    expected_bars = bars[-20:]
    assert average == sum(bar.volume for bar in expected_bars) / 20


def test_get_average_daily_volume_returns_none_when_no_history():
    conn = sqlite3.connect(":memory:")
    repository.init_db(conn)

    assert repository.get_average_daily_volume(conn, "999999") is None
```

(Add `from app.market_data.base import OhlcvBar, Stock` to the imports at the top of `test_repository.py` if not already present — check first with `grep -n "^from\|^import" backend/tests/test_repository.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_repository.py -k average_daily_volume -v`
Expected: FAIL with `AttributeError: module 'app.repository' has no attribute 'get_average_daily_volume'`.

- [ ] **Step 3: Implement the repository helper**

Add to `backend/app/repository.py` right after the `get_price_history` function (around line 1044):

```python
def get_average_daily_volume(conn: sqlite3.Connection, code: str, days: int = 20) -> float | None:
    rows = conn.execute(
        "SELECT volume FROM price_history WHERE code = ? ORDER BY date DESC LIMIT ?",
        (code, days),
    ).fetchall()
    volumes = [row[0] for row in rows if row[0] is not None]
    if not volumes:
        return None
    return sum(volumes) / len(volumes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_repository.py -k average_daily_volume -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests for partial-fill execution**

Add to `backend/tests/test_simulated_executor.py` (add `import os` at the top if not present):

```python
def test_place_buy_order_partially_fills_when_exceeding_volume_cap(conn, monkeypatch):
    from app.market_data.base import OhlcvBar, Stock
    repository.upsert_stocks(conn, [Stock("005930", "삼성전자", "KOSPI")])
    bars = [
        OhlcvBar(date=f"2026-06-{i + 1:02d}", open=70000, high=70000, low=70000, close=70000, volume=100)
        for i in range(20)
    ]
    repository.upsert_price_history(conn, "005930", bars)
    monkeypatch.setenv("SIMULATED_MAX_VOLUME_PARTICIPATION_PCT", "10")

    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    result = executor.place_order("005930", "buy", 50)

    assert result.status == "partial"
    assert result.filled_quantity == 10
    position = repository.get_position(conn, "005930")
    assert position.quantity == 10
    orders = repository.get_orders(conn)
    assert orders[0]["requested_quantity"] == 50
    assert orders[0]["filled_quantity"] == 10
    assert orders[0]["status"] == "partial"
    assert orders[0]["fill_reason"] == "거래량 참여율 한도 초과로 부분체결"


def test_place_buy_order_ignores_volume_cap_when_disabled(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    result = executor.place_order("005930", "buy", 10)

    assert result.status == "filled"
    assert result.filled_quantity is None
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_simulated_executor.py -k volume_cap -v`
Expected: FAIL — `AttributeError`/`AssertionError` since no cap logic or `filled_quantity` field exists yet.

- [ ] **Step 7: Add `filled_quantity` to `OrderResult`**

In `backend/app/execution/base.py:5-15`, add one field:

```python
@dataclass(frozen=True)
class OrderResult:
    order_id: int
    code: str
    side: str
    quantity: int
    fill_price: float | None
    status: str = "filled"
    order_type: str = "market"
    limit_price: float | None = None
    broker_order_id: str | None = None
    filled_quantity: int | None = None
```

- [ ] **Step 8: Implement the volume cap in `SimulatedExecutor`**

In `backend/app/execution/simulated_executor.py`, add `import os` is already present. Add this helper method anywhere among the other `@staticmethod`/instance methods:

```python
    def _volume_cap(self, code: str) -> int | None:
        participation_pct = float(os.getenv("SIMULATED_MAX_VOLUME_PARTICIPATION_PCT", "0"))
        if participation_pct <= 0:
            return None
        avg_volume = repository.get_average_daily_volume(self.conn, code)
        if not avg_volume:
            return None
        cap = int(avg_volume * participation_pct / 100)
        return cap if cap > 0 else None
```

Replace the market-fill branch of `place_order` (currently lines 37-53) with:

```python
        cap = self._volume_cap(code)
        fill_quantity = quantity if cap is None else min(quantity, cap)
        price = self._simulated_fill_price(side, market_price)
        if order_type == "limit" and limit_price is not None:
            price = min(price, limit_price) if side == "buy" else max(price, limit_price)
        fill_status = "filled" if fill_quantity == quantity else "partial"
        fill_reason = None if fill_status == "filled" else "거래량 참여율 한도 초과로 부분체결"
        try:
            self._apply_fill(code, side, fill_quantity, price, commit=False)
            order_id = repository.record_order(
                self.conn, code, side, fill_quantity, price,
                status=fill_status, order_type=order_type, limit_price=limit_price,
                requested_quantity=quantity, filled_quantity=fill_quantity,
                fill_reason=fill_reason, commit=False,
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return OrderResult(
            order_id=order_id, code=code, side=side, quantity=quantity,
            fill_price=price, status=fill_status, order_type=order_type, limit_price=limit_price,
            filled_quantity=fill_quantity if fill_status == "partial" else None,
        )
```

Apply the same cap inside `process_pending_orders` (currently lines 55-73) — replace the loop body's fill section:

```python
    def process_pending_orders(self) -> int:
        filled = 0
        for order in repository.get_pending_orders(self.conn):
            try:
                market_price = self.provider.get_latest_price(order["code"])
                if not self._is_marketable(order["side"], market_price, order["limit_price"]):
                    continue
                cap = self._volume_cap(order["code"])
                fill_quantity = order["quantity"] if cap is None else min(order["quantity"], cap)
                if fill_quantity <= 0:
                    continue
                price = self._simulated_fill_price(order["side"], market_price)
                price = (
                    min(price, order["limit_price"])
                    if order["side"] == "buy"
                    else max(price, order["limit_price"])
                )
                self._apply_fill(order["code"], order["side"], fill_quantity, price, commit=False)
                fill_status = "filled" if fill_quantity == order["quantity"] else "partial"
                fill_reason = None if fill_status == "filled" else "거래량 참여율 한도 초과로 부분체결"
                repository.fill_pending_order(
                    self.conn, order["id"], price, fill_quantity,
                    status=fill_status, fill_reason=fill_reason,
                )
                filled += 1
            except (OrderExecutionError, ValueError):
                continue
        return filled
```

Note `result.status == "partial"` keeps the order queryable but does not re-queue the unfilled remainder — the spec only requires "부분 체결 또는 미체결 처리" (partial fill or no-fill), not automatic re-queueing.

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_simulated_executor.py tests/test_limit_orders.py tests/test_repository.py -v`
Expected: PASS — all existing plus the four new tests.

- [ ] **Step 10: Run full suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS, no regressions elsewhere (in particular `test_autonomous.py`'s cash-deployment test, which does not set `SIMULATED_MAX_VOLUME_PARTICIPATION_PCT` so the cap stays disabled).

- [ ] **Step 11: Commit**

```bash
git add backend/app/repository.py backend/app/execution/base.py backend/app/execution/simulated_executor.py backend/tests/test_repository.py backend/tests/test_simulated_executor.py
git commit -m "feat: cap simulated fills by average daily volume with partial-fill support"
```

---

### Task 3: Multi-period backtest comparison with profit factor and turnover

**Files:**
- Modify: `backend/app/ai/backtest.py`
- Modify: `backend/app/api/agent.py:134-136` (add one route)
- Test: `backend/tests/test_autonomous.py`

**Interfaces:**
- Consumes: `run_walk_forward_backtest(conn, days, universe_size)` (existing, modified return shape only — adds fields, does not remove or rename any).
- Produces: `run_walk_forward_backtest(...)` now also returns `profit_factor` (float or `None`) and `turnover_pct` (float); new function `run_multi_period_backtest(conn, periods=(60, 120, 252), universe_size=50) -> dict` returning `{"periods": [<single-period result + "period_days" + "verdict">, ...], "overall_verdict": "pass"|"warn"|"fail"}`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_autonomous.py` (uses `run_walk_forward_backtest`, already imported; add `run_multi_period_backtest` to the import line at the top: `from app.ai.backtest import run_walk_forward_backtest, run_multi_period_backtest`):

```python
def test_backtest_reports_profit_factor_and_turnover(tmp_path):
    db_path = str(tmp_path / "profit-factor.db")
    _seed_uptrend(db_path)
    conn = sqlite3.connect(db_path)

    result = run_walk_forward_backtest(conn, days=30, universe_size=10)

    assert "profit_factor" in result
    assert "turnover_pct" in result
    assert result["turnover_pct"] >= 0
    conn.close()


def test_multi_period_backtest_runs_each_period_and_returns_verdict(tmp_path):
    db_path = str(tmp_path / "multi-period.db")
    _seed_uptrend(db_path)
    conn = sqlite3.connect(db_path)

    result = run_multi_period_backtest(conn, periods=(10, 20), universe_size=10)

    assert [period["period_days"] for period in result["periods"]] == [10, 20]
    assert all(period["verdict"] in {"pass", "warn", "fail"} for period in result["periods"])
    assert result["overall_verdict"] in {"pass", "warn", "fail"}
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_autonomous.py -k "profit_factor or multi_period" -v`
Expected: FAIL — `profit_factor`/`turnover_pct` missing from result dict, `run_multi_period_backtest` does not exist.

- [ ] **Step 3: Add profit factor and turnover to `run_walk_forward_backtest`**

In `backend/app/ai/backtest.py`, add a `traded_value` accumulator. In the sell loop (around line 77-82), change:

```python
            if should_sell:
                fill = _fill_price("sell", open_price)
                cash += fill * position["quantity"]
                traded_value += fill * position["quantity"]
                realized_returns.append((fill - position["avg_price"]) / position["avg_price"] * 100)
                trade_count += 1
                del positions[code]
```

In the buy loop (around line 104-115), change:

```python
            fill = _fill_price("buy", open_price)
            remaining_signals = len(selected_signals) - index
            allocation = min(
                cash / remaining_signals,
                initial_capital * max_position_pct / 100,
            )
            quantity = int(allocation // fill)
            if quantity <= 0:
                continue
            cash -= fill * quantity
            traded_value += fill * quantity
            positions[signal["code"]] = {"quantity": quantity, "avg_price": fill}
            trade_count += 1
```

Initialize the accumulator alongside `trade_count = 0` (line 32): `traded_value = 0.0`.

Replace the final return dict's construction (lines 146-171) by adding two computed values before the `return` and two new keys inside it:

```python
    gains = sum(value for value in realized_returns if value > 0)
    losses = sum(-value for value in realized_returns if value < 0)
    profit_factor = (gains / losses) if losses > 0 else (None if gains == 0 else float("inf"))
    turnover_pct = (traded_value / initial_capital * 100) if initial_capital else 0.0

    return {
        "mode": "walk_forward_daily",
        "start_date": all_dates[0],
        "end_date": all_dates[-1],
        "trading_days": len(all_dates),
        "universe_size": len(codes),
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return_pct": (final_value - initial_capital) / initial_capital * 100,
        "equal_weight_benchmark_pct": benchmark_return,
        "alpha_pct": (final_value - initial_capital) / initial_capital * 100 - benchmark_return,
        "max_drawdown_pct": max_drawdown,
        "trade_count": trade_count,
        "closed_trade_count": len(realized_returns),
        "win_rate_pct": (
            sum(value > 0 for value in realized_returns) / len(realized_returns) * 100
            if realized_returns else 0
        ),
        "profit_factor": profit_factor,
        "turnover_pct": turnover_pct,
        "open_positions": len(positions),
        "equity_curve": equity_curve,
        "costs_bps": {
            "slippage": float(os.getenv("SIMULATED_SLIPPAGE_BPS", "0")),
            "commission": float(os.getenv("SIMULATED_COMMISSION_BPS", "0")),
            "sell_tax": float(os.getenv("SIMULATED_SELL_TAX_BPS", "0")),
        },
    }
```

Also add `"profit_factor": None, "turnover_pct": 0.0,` to `_empty_result` (around line 190-207).

- [ ] **Step 4: Add `run_multi_period_backtest`**

Append to `backend/app/ai/backtest.py`:

```python
def _verdict(result: dict) -> str:
    if result["max_drawdown_pct"] <= -20 or result["alpha_pct"] <= -10:
        return "fail"
    if result["max_drawdown_pct"] <= -12 or result["alpha_pct"] < 0:
        return "warn"
    return "pass"


def run_multi_period_backtest(
    conn, periods: tuple[int, ...] = (60, 120, 252), universe_size: int = 50
) -> dict:
    period_results = []
    for period_days in periods:
        result = run_walk_forward_backtest(conn, days=period_days, universe_size=universe_size)
        period_results.append({**result, "period_days": period_days, "verdict": _verdict(result)})

    verdict_rank = {"pass": 0, "warn": 1, "fail": 2}
    overall_verdict = max(
        (period["verdict"] for period in period_results),
        key=lambda verdict: verdict_rank[verdict],
        default="pass",
    )
    return {"periods": period_results, "overall_verdict": overall_verdict}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_autonomous.py -v`
Expected: PASS, all tests in the file including the two new ones.

- [ ] **Step 6: Add the comparison endpoint**

In `backend/app/api/agent.py`, add `run_multi_period_backtest` to the existing import at line 20 (`from ..ai.backtest import run_walk_forward_backtest, run_multi_period_backtest`), and add a new route right after the existing one at line 134-136:

```python
@router.get("/agent/autonomous/backtest/compare")
def run_autonomous_backtest_comparison(request: Request, universe: int = 50):
    return run_multi_period_backtest(request.app.state.conn, periods=(60, 120, 252), universe_size=universe)
```

- [ ] **Step 7: Write a failing API test, then verify it passes**

Check `backend/tests/test_api_agent.py` for the existing backtest endpoint test pattern first (`grep -n "backtest" backend/tests/test_api_agent.py`), then add a matching test:

```python
def test_autonomous_backtest_compare_returns_multi_period_verdicts(client_with_seeded_history):
    response = client_with_seeded_history.get("/agent/autonomous/backtest/compare?universe=10")
    assert response.status_code == 200
    body = response.json()
    assert len(body["periods"]) == 3
    assert body["overall_verdict"] in {"pass", "warn", "fail"}
```

If no `client_with_seeded_history` fixture exists yet, follow whatever fixture the existing `/agent/autonomous/backtest` test in the same file already uses instead — match its exact setup rather than inventing a new one.

Run: `cd backend && uv run pytest tests/test_api_agent.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/ai/backtest.py backend/app/api/agent.py backend/tests/test_autonomous.py backend/tests/test_api_agent.py
git commit -m "feat: add multi-period backtest comparison with profit factor and turnover"
```

---

### Task 4: AI no-action and block-reason explanation

**Files:**
- Modify: `backend/app/api/agent.py:238-344` (`_direct_factual_answer`)
- Test: `backend/tests/test_api_agent.py`

**Interfaces:**
- Consumes: `engine_status["latest_cycle"]` — already contains `market_regime: str | None`, `target_exposure_pct: float | None`, `blocked_decisions: list[dict]` (each `{"code", "action", "rule", "reason"}`), per `repository.get_autonomous_cycles` (`backend/app/repository.py:1239-1262`, confirmed present in the DB and already returned by `AutonomousTradingEngine.status()`).
- Produces: no new function signatures — adds one more `if` branch inside the existing `_direct_factual_answer(conn, risk, prompt, engine_status) -> str | None` function, following the exact pattern of the branches already there (`왜샀` etc., lines 252-343).

- [ ] **Step 1: Write the failing tests**

First check the existing test file's setup pattern with `grep -n "_direct_factual_answer\|def test_agent_chat" backend/tests/test_api_agent.py` to match its exact `app.state` wiring (provider/executor/conn fixtures), then add:

```python
def test_agent_chat_explains_blocked_buy_from_latest_cycle(monkeypatch):
    # follow the same app/client/conn setup as the neighboring
    # test_agent_chat_returns_answer_without_executing_when_auto_disabled test
    ...
    repository.insert_autonomous_cycle(
        conn,
        started_at="2026-09-01T00:00:00+00:00",
        status="observed",
        market_open=True,
        decisions="[]",
        order_ids="[]",
        total_value=1_000_000,
        error=None,
        market_regime="bearish",
        target_exposure_pct=20.0,
        blocked_decisions=json.dumps([
            {"code": "005930", "action": "buy", "rule": "bearish_regime", "reason": "하락장으로 분류되어 신규 매수 중단"}
        ], ensure_ascii=False),
    )

    response = client.post("/agent/chat", json={"prompt": "오늘 왜 아무것도 안 샀어?", "scope": "dashboard"})

    assert response.status_code == 200
    body = response.json()
    assert "bearish_regime" not in body["answer"]
    assert "하락장" in body["answer"]
    assert "20" in body["answer"]
```

Write out the full test using whatever fixture the neighboring test in the file actually uses for `client`/`conn` — do not invent a different app-construction path. The literal assertion values (`"하락장"`, `"20"`) must match whatever wording Step 3 below produces exactly, so write this test after Step 3 if it's easier to keep them in sync, but it must fail first per TDD.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_api_agent.py -k blocked_buy -v`
Expected: FAIL — no such explanation branch exists, the model would be asked to guess instead (or the direct-answer path returns `None` and falls through to the LLM call).

- [ ] **Step 3: Implement the explanation branch**

In `backend/app/api/agent.py`, add this branch inside `_direct_factual_answer`, right before the final `return None` (line 344):

```python
    if any(marker in normalized for marker in ("왜안샀", "왜아무것도안했", "왜관망", "매수안한이유")):
        cycle = engine_status.get("latest_cycle") or {}
        blocked_buys = [
            item for item in (cycle.get("blocked_decisions") or [])
            if item.get("action") == "buy"
        ]
        regime = cycle.get("market_regime") or "확인 불가"
        target_exposure = cycle.get("target_exposure_pct")
        target_exposure_text = f"{target_exposure:.1f}%" if target_exposure is not None else "확인 불가"
        if not blocked_buys:
            return (
                f"최근 자율운용 사이클(#{cycle.get('id', '없음')})에서 차단된 매수 판단이 없습니다. "
                f"시장 국면은 {regime}, 목표 투자비중은 {target_exposure_text}입니다.\n조회 시각: {queried_at}"
            )
        reasons = "; ".join(
            f"{item.get('code') or '전체'} - {item.get('reason', '사유 없음')}"
            for item in blocked_buys
        )
        return (
            f"최근 자율운용 사이클(#{cycle.get('id', '없음')})은 시장 국면 {regime}, "
            f"목표 투자비중 {target_exposure_text} 기준으로 다음 매수를 차단했습니다: {reasons}\n"
            f"조회 시각: {queried_at}"
        )

    if any(marker in normalized for marker in ("현재장세", "시장국면", "목표비중", "목표투자비중")):
        cycle = engine_status.get("latest_cycle") or {}
        regime = cycle.get("market_regime") or "확인 불가"
        target_exposure = cycle.get("target_exposure_pct")
        target_exposure_text = f"{target_exposure:.1f}%" if target_exposure is not None else "확인 불가"
        return (
            f"현재 시장 국면은 {regime}이며 목표 투자비중은 {target_exposure_text}입니다.\n"
            f"조회 시각: {queried_at}"
        )
```

Note: place these two new branches before the existing `("ai상태", ...)` branch so more specific "why didn't buy" phrasing isn't swallowed by the generic engine-status branch first (their marker sets don't overlap, so order only matters for readability, not correctness — but keep them together for clarity).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_api_agent.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/agent.py backend/tests/test_api_agent.py
git commit -m "feat: answer AI copilot no-action and block-reason questions from recorded cycle data"
```

---

### Task 5: Integration sweep, README, and service rollout

**Files:**
- Modify: `README.md` (env var reference table)
- No code changes — verification and documentation only

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: nothing new — this task verifies the whole branch together and documents the new env vars for real deployment.

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS, 100% (starting count was 111; should now be 111 + new tests from Tasks 1-4, all green).

- [ ] **Step 2: Document new env vars**

In `README.md`, find the existing env var reference block containing `AI_AUTONOMOUS_STOP_LOSS_PCT` / `SIMULATED_SLIPPAGE_BPS` (around line 61-72) and add three lines immediately after the `SIMULATED_*_BPS` group:

```
AI_CANDIDATE_STALE_DAYS=9999
AI_CANDIDATE_MIN_AVG_TRADING_VALUE=0
SIMULATED_MAX_VOLUME_PARTICIPATION_PCT=0
```

Add one short sentence above the block (matching the existing doc's tone) noting these three default to disabled and must be set explicitly to activate liquidity/staleness filtering and volume-capped fills.

- [ ] **Step 3: Restart the 24/7 service so new code takes effect**

Run:
```bash
launchctl unload ~/Library/LaunchAgents/com.kis-paper-trading.backend.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.kis-paper-trading.backend.plist
sleep 3
curl -s http://127.0.0.1:8000/health
```
Expected: `{"status":"ok"}` (or equivalent 200 response) confirming the service picked up the new code.

If `~/Library/LaunchAgents/com.kis-paper-trading.backend.plist` doesn't exist yet (the checked-in one lives at `ops/com.kis-paper-trading.backend.plist` and may not be symlinked/copied into LaunchAgents), skip this step and just confirm the existing dev-server process (however it's currently running per `ops/README.md`) is serving `/health` with a 200.

- [ ] **Step 4: Manually verify the new endpoints once against the live service**

```bash
curl -s http://127.0.0.1:8000/agent/autonomous/backtest/compare?universe=10
curl -s -X POST http://127.0.0.1:8000/agent/chat -H 'Content-Type: application/json' -d '{"prompt": "오늘 왜 아무것도 안 샀어?", "scope": "dashboard"}'
```
Expected: both return 200 with the new fields (`periods`/`overall_verdict` for the first; an `answer` string mentioning market regime/target exposure or "차단된 매수 판단이 없습니다" for the second — do not place any real orders, this is a read-only chat query).

- [ ] **Step 5: Commit and push**

```bash
git add README.md
git commit -m "docs: document new liquidity, volume-cap, and staleness env vars"
git push
```

Per standing project convention, push immediately after this commit — do not leave it local-only.
