import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app import repository
from app.ai.autonomous import AutonomousTradingEngine, is_regular_market_open
from app.ai.backtest import run_walk_forward_backtest, run_multi_period_backtest
from app.market_data.base import OhlcvBar, Stock

KST = ZoneInfo("Asia/Seoul")


class FixedPriceProvider:
    def __init__(self, price=1000.0):
        self.price = price

    def get_latest_price(self, code):
        return self.price


def _seed_uptrend(db_path):
    conn = sqlite3.connect(db_path)
    repository.init_db(conn, 1_000_000)
    repository.upsert_stocks(conn, [Stock("005930", "삼성전자", "KOSPI")])
    bars = [
        OhlcvBar(
            date=f"2026-06-{index + 1:02d}",
            open=900 + index,
            high=910 + index,
            low=890 + index,
            close=900 + index * 2,
            volume=1000 + index,
        )
        for index in range(30)
    ]
    repository.upsert_price_history(conn, "005930", bars)
    conn.close()


def _seed_diversified_uptrends(db_path):
    conn = sqlite3.connect(db_path)
    repository.init_db(conn, 1_000_000)
    stocks = [Stock(f"00000{index}", f"상승종목{index}", "KOSPI") for index in range(1, 6)]
    repository.upsert_stocks(conn, stocks)
    for stock in stocks:
        bars = [
            OhlcvBar(
                date=f"2026-06-{index + 1:02d}", open=900 + index, high=920 + index,
                low=890 + index, close=900 + index * 2, volume=10_000 + index,
            )
            for index in range(30)
        ]
        repository.upsert_price_history(conn, stock.code, bars)
    conn.close()


def test_regular_market_hours_are_separate_from_24h_process_uptime():
    assert is_regular_market_open(datetime(2026, 8, 31, 10, 0, tzinfo=KST)) is True
    assert is_regular_market_open(datetime(2026, 8, 31, 20, 0, tzinfo=KST)) is False
    assert is_regular_market_open(datetime(2026, 8, 30, 10, 0, tzinfo=KST)) is False


def test_market_regime_blocks_new_risk_when_breadth_is_bearish():
    candidates = [
        {"score": -50}, {"score": -40}, {"score": -30}, {"score": 30},
    ]
    assert AutonomousTradingEngine._market_regime(candidates) == "bearish"


def test_target_exposure_changes_by_regime_and_drawdown(monkeypatch):
    monkeypatch.setenv("AI_BULLISH_TARGET_EXPOSURE_PCT", "100")
    monkeypatch.setenv("AI_NEUTRAL_TARGET_EXPOSURE_PCT", "80")
    monkeypatch.setenv("AI_BEARISH_TARGET_EXPOSURE_PCT", "20")

    assert AutonomousTradingEngine._target_exposure_pct(
        "bullish", {"max_drawdown_pct": -1}
    ) == 100
    assert AutonomousTradingEngine._target_exposure_pct(
        "neutral", {"max_drawdown_pct": -5.5}
    ) == 50
    assert AutonomousTradingEngine._target_exposure_pct(
        "bullish", {"max_drawdown_pct": -7.5}
    ) == 30
    assert AutonomousTradingEngine._target_exposure_pct(
        "bullish", {"max_drawdown_pct": -10}
    ) == 0


def test_autonomous_cycle_does_not_trade_when_market_is_closed(tmp_path, monkeypatch):
    db_path = str(tmp_path / "closed.db")
    _seed_uptrend(db_path)
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    engine = AutonomousTradingEngine(db_path, FixedPriceProvider())
    engine.set_enabled(True)

    result = engine.run_cycle(datetime(2026, 8, 31, 20, 0, tzinfo=KST))

    assert result["status"] == "market_closed"
    assert result["order_ids"] == []


def test_autonomous_cycle_filters_model_decision_and_places_paper_order(tmp_path, monkeypatch):
    db_path = str(tmp_path / "open.db")
    _seed_uptrend(db_path)
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(
        "app.ai.autonomous.ask_local_model",
        lambda system, prompt: (
            "상승 추세를 확인했습니다.\n"
            '```json\n{"decisions":[{"code":"005930","action":"buy","reason":"추세 확인"}]}\n```'
        ),
    )
    engine = AutonomousTradingEngine(db_path, FixedPriceProvider())
    engine.set_enabled(True)

    result = engine.run_cycle(datetime(2026, 8, 31, 10, 0, tzinfo=KST))

    assert result["error"] is None, result["error"]
    assert result["status"] == "executed", result
    assert len(result["order_ids"]) == 1
    conn = sqlite3.connect(db_path)
    assert repository.get_position(conn, "005930") is not None
    assert repository.get_autonomous_cycles(conn, 1)[0]["status"] == "executed"
    conn.close()


def test_autonomous_cycle_cooldown_prevents_repeated_buy(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cooldown.db")
    _seed_uptrend(db_path)
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_AUTONOMOUS_COOLDOWN_MINUTES", "60")
    monkeypatch.setattr(
        "app.ai.autonomous.ask_local_model",
        lambda system, prompt: '```json\n{"decisions":[{"code":"005930","action":"buy","reason":"추세"}]}\n```',
    )
    engine = AutonomousTradingEngine(db_path, FixedPriceProvider())
    engine.set_enabled(True)

    first = engine.run_cycle(datetime(2026, 8, 31, 10, 0, tzinfo=KST))
    second = engine.run_cycle(datetime(2026, 8, 31, 10, 5, tzinfo=KST))

    assert len(first["order_ids"]) == 1
    assert second["status"] == "observed"
    assert second["order_ids"] == []
    assert any(item["rule"] == "cooldown" for item in second["blocked_decisions"])

    conn = sqlite3.connect(db_path)
    latest_cycle = repository.get_autonomous_cycles(conn, 1)[0]
    assert latest_cycle["market_regime"] == "bullish"
    assert latest_cycle["target_exposure_pct"] == 100
    assert any(item["rule"] == "cooldown" for item in latest_cycle["blocked_decisions"])
    conn.close()


def test_neutral_regime_limits_cash_deployment_to_target_exposure(tmp_path, monkeypatch):
    db_path = str(tmp_path / "neutral-target.db")
    _seed_diversified_uptrends(db_path)
    monkeypatch.setenv("AI_NEUTRAL_TARGET_EXPOSURE_PCT", "80")
    monkeypatch.setenv("AI_AUTONOMOUS_MAX_ORDERS_PER_CYCLE", "5")
    monkeypatch.setenv("AI_MAX_POSITION_PCT", "20")
    engine = AutonomousTradingEngine(db_path, FixedPriceProvider())
    conn = sqlite3.connect(db_path)
    risk = {
        "total_value": 1_000_000,
        "cash": 1_000_000,
        "evaluated_value": 0,
        "positions": [],
        "max_drawdown_pct": 0,
    }
    candidates = [
        {"code": f"00000{index}", "score": 50, "change_pct": 1}
        for index in range(1, 6)
    ]

    decisions, blocked = engine._guard_decisions(
        conn,
        risk,
        candidates,
        [{"code": "000001", "action": "buy", "reason": "추세"}],
        "neutral",
        80,
    )

    assert sum(item["quantity"] * 1000 for item in decisions) == 800_000
    assert blocked == []
    conn.close()


def test_autonomous_cycle_deploys_all_available_cash_across_candidates(tmp_path, monkeypatch):
    db_path = str(tmp_path / "fully-invested.db")
    _seed_diversified_uptrends(db_path)
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_AUTONOMOUS_MAX_ORDERS_PER_CYCLE", "5")
    monkeypatch.setenv("AI_AUTONOMOUS_CASH_RESERVE_PCT", "0")
    monkeypatch.setenv("AI_MAX_POSITION_PCT", "20")
    monkeypatch.setenv("SIMULATED_SLIPPAGE_BPS", "0")
    monkeypatch.setenv("SIMULATED_COMMISSION_BPS", "0")
    monkeypatch.setattr(
        "app.ai.autonomous.ask_local_model",
        lambda system, prompt: '```json\n{"decisions":[{"code":"000001","action":"buy","reason":"최우선"}]}\n```',
    )
    engine = AutonomousTradingEngine(db_path, FixedPriceProvider())
    engine.set_enabled(True)

    result = engine.run_cycle(datetime(2026, 8, 31, 10, 0, tzinfo=KST))

    conn = sqlite3.connect(db_path)
    assert len(result["order_ids"]) == 5
    assert repository.get_cash_balance(conn) < 1000
    assert len(repository.get_all_positions(conn)) == 5
    conn.close()


def test_walk_forward_backtest_uses_previous_data_and_returns_metrics(tmp_path, monkeypatch):
    db_path = str(tmp_path / "backtest.db")
    _seed_uptrend(db_path)
    monkeypatch.setenv("SIMULATED_SLIPPAGE_BPS", "5")
    monkeypatch.setenv("SIMULATED_COMMISSION_BPS", "1.5")
    monkeypatch.setenv("SIMULATED_SELL_TAX_BPS", "15")
    conn = sqlite3.connect(db_path)

    result = run_walk_forward_backtest(conn, days=30, universe_size=10)

    assert result["mode"] == "walk_forward_daily"
    assert result["trading_days"] == 30
    assert result["trade_count"] >= 1
    assert result["final_value"] > 0
    assert result["costs_bps"]["slippage"] == 5
    assert "equal_weight_benchmark_pct" in result
    assert "alpha_pct" in result
    conn.close()


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


def test_walk_forward_backtest_skips_zero_open_prices(tmp_path):
    db_path = str(tmp_path / "zero-open.db")
    _seed_uptrend(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE price_history SET open = 0 WHERE code = ? AND date = ?", ("005930", "2026-06-30"))
    conn.commit()

    result = run_walk_forward_backtest(conn, days=30, universe_size=10)

    assert result["final_value"] > 0
    conn.close()
