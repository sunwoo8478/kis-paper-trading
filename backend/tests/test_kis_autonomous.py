import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import repository
from app.ai.kis_autonomous import KisPaperAutonomousEngine
from app.execution.kis_paper_executor import KisPaperExecutor
from app.integrations.kis import KisApiError
from app.market_data.base import OhlcvBar, Stock


KST = ZoneInfo("Asia/Seoul")


class _Provider:
    def get_latest_price(self, code):
        return 1000.0


class _Client:
    def __init__(self, order_enabled=True, broker_orders=None):
        self.order_enabled = order_enabled
        self.orders = []
        self.broker_orders = broker_orders or []
        self.buying_power_cash = 10**12

    def status(self):
        return {
            "configured": True,
            "authenticated": True,
            "account_configured": True,
            "order_enabled": self.order_enabled,
        }

    def get_balance(self):
        return {
            "cash": 500_000_000.0,
            "total_value": 500_000_000.0,
            "evaluated_value": 0.0,
            "positions": [],
        }

    def get_daily_orders(self):
        return self.broker_orders

    def get_buying_power(self, code, price=None):
        return {"orderable_cash": self.buying_power_cash, "reference_price": price or 1000.0}

    def place_cash_order(self, code, side, quantity, order_type, limit_price):
        self.orders.append({"code": code, "side": side, "quantity": quantity})
        return {
            "broker_order_id": str(10000 + len(self.orders)),
            "status": "submitted",
        }


def _seed(db_path):
    conn = sqlite3.connect(db_path)
    repository.init_db(conn)
    repository.upsert_stocks(conn, [Stock("005930", "삼성전자", "KOSPI")])
    repository.upsert_price_history(
        conn,
        "005930",
        [
            OhlcvBar(
                date=f"2026-08-{index + 1:02d}",
                open=900 + index,
                high=920 + index,
                low=890 + index,
                close=900 + index * 2,
                volume=100_000,
            )
            for index in range(30)
        ],
    )
    conn.close()


def test_kis_executor_records_broker_order(tmp_path):
    db_path = str(tmp_path / "executor.db")
    _seed(db_path)
    conn = sqlite3.connect(db_path)
    client = _Client()
    executor = KisPaperExecutor(client, conn)

    result = executor.place_order("005930", "buy", 1, reason="카나리")

    assert result.broker_order_id == "10001"
    order = repository.get_kis_paper_orders(conn, 1)[0]
    assert order["broker_order_id"] == "10001"
    assert order["reason"] == "카나리"
    conn.close()


def test_kis_engine_refuses_enable_while_order_is_locked(tmp_path):
    db_path = str(tmp_path / "locked.db")
    _seed(db_path)
    engine = KisPaperAutonomousEngine(db_path, _Provider(), _Client(False))

    with pytest.raises(KisApiError, match="주문 활성화"):
        engine.set_enabled(True)


def test_kis_engine_uses_kis_balance_and_records_separate_cycle(
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "cycle.db")
    _seed(db_path)
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("KIS_PAPER_MAX_ORDERS_PER_CYCLE", "1")
    monkeypatch.setattr(
        "app.ai.kis_autonomous.ask_local_model",
        lambda system, prompt: (
            '```json\n{"decisions":[{"code":"005930","action":"buy","reason":"추세 확인"}]}\n```'
        ),
    )
    client = _Client(True)
    engine = KisPaperAutonomousEngine(db_path, _Provider(), client)
    engine.set_enabled(True)

    result = engine.run_cycle(datetime(2026, 9, 1, 10, 0, tzinfo=KST))

    assert result["status"] == "executed", result
    assert result["broker_order_ids"] == ["10001"]
    assert client.orders[0]["quantity"] == 100_000
    conn = sqlite3.connect(db_path)
    assert repository.get_kis_paper_cycles(conn, 1)[0]["status"] == "executed"
    assert len(repository.get_kis_paper_orders(conn, 10)) == 1
    assert repository.get_orders(conn) == []
    conn.close()


def test_kis_cash_reserve_limits_buy_deployment(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cash-reserve.db")
    _seed(db_path)
    monkeypatch.setenv("KIS_PAPER_CASH_RESERVE_PCT", "20")
    monkeypatch.setenv("KIS_PAPER_MAX_POSITION_PCT", "100")
    engine = KisPaperAutonomousEngine(db_path, _Provider(), _Client())
    conn = sqlite3.connect(db_path)
    risk = {
        "total_value": 1_000_000, "cash": 1_000_000, "evaluated_value": 0,
        "positions": [], "max_drawdown_pct": 0,
    }
    candidates = [{"code": "005930", "score": 50, "change_pct": 1}]

    decisions, blocked = engine._guard_decisions(
        conn, risk, candidates,
        [{"code": "005930", "action": "buy", "reason": "추세"}],
        "neutral", 100,
    )

    assert sum(item["quantity"] * 1000 for item in decisions) == 800_000
    conn.close()


def test_kis_buy_quantity_capped_by_volume_participation(tmp_path, monkeypatch):
    db_path = str(tmp_path / "volume-cap.db")
    _seed(db_path)
    monkeypatch.setenv("KIS_PAPER_MAX_VOLUME_PARTICIPATION_PCT", "1")
    monkeypatch.setenv("KIS_PAPER_MAX_POSITION_PCT", "100")
    engine = KisPaperAutonomousEngine(db_path, _Provider(), _Client())
    conn = sqlite3.connect(db_path)
    risk = {
        "total_value": 100_000_000, "cash": 100_000_000, "evaluated_value": 0,
        "positions": [], "max_drawdown_pct": 0,
    }
    candidates = [{"code": "005930", "score": 50, "change_pct": 1}]

    decisions, blocked = engine._guard_decisions(
        conn, risk, candidates,
        [{"code": "005930", "action": "buy", "reason": "추세"}],
        "neutral", 100,
    )

    assert decisions[0]["quantity"] == 1000
    conn.close()


def test_kis_buy_quantity_uncapped_when_volume_participation_disabled(tmp_path):
    db_path = str(tmp_path / "volume-cap-disabled.db")
    _seed(db_path)
    engine = KisPaperAutonomousEngine(db_path, _Provider(), _Client())
    conn = sqlite3.connect(db_path)
    risk = {
        "total_value": 100_000_000, "cash": 100_000_000, "evaluated_value": 0,
        "positions": [], "max_drawdown_pct": 0,
    }
    candidates = [{"code": "005930", "score": 50, "change_pct": 1}]

    decisions, blocked = engine._guard_decisions(
        conn, risk, candidates,
        [{"code": "005930", "action": "buy", "reason": "추세"}],
        "neutral", 100,
    )

    assert decisions[0]["quantity"] == 20_000
    conn.close()


def test_kis_rotation_sell_exits_weakening_position_even_without_stop_loss(tmp_path, monkeypatch):
    db_path = str(tmp_path / "rotation-sell.db")
    _seed(db_path)
    monkeypatch.setenv("KIS_PAPER_ROTATION_SELL_SCORE", "-10")
    monkeypatch.setenv("KIS_PAPER_STOP_LOSS_PCT", "50")
    monkeypatch.setattr(
        "app.ai.kis_autonomous.calculate_stock_analytics",
        lambda history: {"technical_bias": {"score": -30}, "momentum": {"rsi14": 40, "macd_histogram": 0}},
    )
    engine = KisPaperAutonomousEngine(db_path, _Provider(), _Client())
    conn = sqlite3.connect(db_path)
    risk = {
        "total_value": 1_000_000, "cash": 500_000, "evaluated_value": 500_000,
        "positions": [{"code": "005930", "name": "삼성전자", "quantity": 10, "avg_price": 990.0, "return_pct": -1.0}],
        "max_drawdown_pct": 0,
    }

    decisions, blocked = engine._guard_decisions(conn, risk, [], [], "neutral", 80)

    assert any(item["code"] == "005930" and item["action"] == "sell" for item in decisions)
    conn.close()


def test_kis_rotation_sell_disabled_by_default(tmp_path, monkeypatch):
    db_path = str(tmp_path / "rotation-sell-disabled.db")
    _seed(db_path)
    monkeypatch.setattr(
        "app.ai.kis_autonomous.calculate_stock_analytics",
        lambda history: {"technical_bias": {"score": -30}, "momentum": {"rsi14": 40, "macd_histogram": 0}},
    )
    engine = KisPaperAutonomousEngine(db_path, _Provider(), _Client())
    conn = sqlite3.connect(db_path)
    risk = {
        "total_value": 1_000_000, "cash": 500_000, "evaluated_value": 500_000,
        "positions": [{"code": "005930", "name": "삼성전자", "quantity": 10, "avg_price": 990.0, "return_pct": -1.0}],
        "max_drawdown_pct": 0,
    }

    decisions, blocked = engine._guard_decisions(conn, risk, [], [], "neutral", 80)

    assert not any(item["code"] == "005930" and item["action"] == "sell" for item in decisions)
    conn.close()


def test_execute_caps_buy_quantity_to_realtime_orderable_cash(tmp_path):
    db_path = str(tmp_path / "realtime-cap.db")
    _seed(db_path)
    client = _Client()
    client.buying_power_cash = 5000
    engine = KisPaperAutonomousEngine(db_path, _Provider(), client)
    conn = sqlite3.connect(db_path)

    order_ids = engine._execute(conn, [{"code": "005930", "action": "buy", "quantity": 100, "reason": "test"}])

    assert len(order_ids) == 1
    assert client.orders[0]["quantity"] == 5
    conn.close()


def test_execute_skips_buy_when_no_realtime_orderable_cash(tmp_path):
    db_path = str(tmp_path / "realtime-zero.db")
    _seed(db_path)
    client = _Client()
    client.buying_power_cash = 0
    engine = KisPaperAutonomousEngine(db_path, _Provider(), client)
    conn = sqlite3.connect(db_path)

    order_ids = engine._execute(conn, [{"code": "005930", "action": "buy", "quantity": 100, "reason": "test"}])

    assert order_ids == []
    assert client.orders == []
    conn.close()


def test_execute_does_not_cap_sell_decisions(tmp_path):
    db_path = str(tmp_path / "realtime-sell.db")
    _seed(db_path)
    client = _Client()
    client.buying_power_cash = 0
    engine = KisPaperAutonomousEngine(db_path, _Provider(), client)
    conn = sqlite3.connect(db_path)

    order_ids = engine._execute(conn, [{"code": "005930", "action": "sell", "quantity": 10, "reason": "test"}])

    assert len(order_ids) == 1
    assert client.orders[0]["quantity"] == 10
    conn.close()


def test_kis_engine_waits_while_broker_order_has_remaining_quantity(
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "pending.db")
    _seed(db_path)
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(
        "app.ai.kis_autonomous.ask_local_model",
        lambda system, prompt: '```json\n{"decisions":[]}\n```',
    )
    broker_order = {
        "broker_order_id": "12345",
        "branch_code": "00950",
        "code": "005930",
        "name": "삼성전자",
        "side": "buy",
        "requested_quantity": 10,
        "filled_quantity": 3,
        "remaining_quantity": 7,
        "avg_fill_price": 1000,
        "status": "partial",
    }
    client = _Client(True, [broker_order])
    conn = sqlite3.connect(db_path)
    repository.insert_kis_paper_order(
        conn,
        broker_order_id="12345",
        code="005930",
        side="buy",
        quantity=10,
        order_type="market",
        limit_price=None,
        status="submitted",
        reason="테스트",
    )
    conn.close()
    engine = KisPaperAutonomousEngine(db_path, _Provider(), client)
    engine.set_enabled(True)

    result = engine.run_cycle(datetime(2026, 9, 1, 10, 0, tzinfo=KST))

    assert result["error"] is None, result["error"]
    assert result["status"] == "pending_orders", result
    assert result["broker_order_ids"] == []
    assert result["blocked_decisions"][0]["rule"] == "open_broker_order"
    assert client.orders == []
    conn = sqlite3.connect(db_path)
    stored = repository.get_kis_paper_orders(conn, 1)[0]
    assert stored["filled_quantity"] == 3
    assert stored["remaining_quantity"] == 7
    conn.close()


def test_guard_skips_open_order_stock_and_uses_other_candidate(tmp_path):
    db_path = str(tmp_path / "open-order-other-stock.db")
    _seed(db_path)
    engine = KisPaperAutonomousEngine(db_path, _Provider(), _Client())
    conn = sqlite3.connect(db_path)
    risk = {
        "total_value": 1_000_000,
        "cash": 500_000,
        "evaluated_value": 500_000,
        "positions": [],
        "max_drawdown_pct": 0,
    }
    candidates = [
        {"code": "005930", "score": 80, "change_pct": 1.0},
        {"code": "000660", "score": 70, "change_pct": 1.0},
    ]

    decisions, blocked = engine._guard_decisions(
        conn,
        risk,
        candidates,
        [
            {"code": "005930", "action": "buy", "reason": "test"},
            {"code": "000660", "action": "buy", "reason": "test"},
        ],
        "neutral",
        100,
        open_order_codes={"005930"},
    )

    assert [item["code"] for item in decisions] == ["000660"]
    assert any(item["code"] == "005930" for item in blocked)
    conn.close()


def test_rank_candidates_excludes_recent_nontradable_symbol_and_uses_configured_pool(
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "candidate-pool.db")
    _seed(db_path)
    engine = KisPaperAutonomousEngine(db_path, _Provider(), _Client())
    conn = sqlite3.connect(db_path)
    candidates = [
        {
            "code": f"{index:06d}",
            "name": f"후보{index}",
            "market": "KOSPI",
            "last_price": 1000,
            "prev_close": 990,
            "change_pct": 1.0,
            "volume": 100_000,
        }
        for index in range(20)
    ]
    candidates[0]["code"] = "368600"
    repository.insert_kis_paper_cycle(
        conn,
        started_at=datetime.now().isoformat(),
        status="observed",
        market_open=True,
        market_regime="bullish",
        target_exposure_pct=100,
        decisions=[{
            "code": "368600",
            "action": "buy",
            "quantity": 1,
            "execution_error": "KIS API 오류 [40070000]: 매매불가 종목",
        }],
        blocked_decisions=[],
        broker_order_ids=[],
        total_value=500_000_000,
        error=None,
    )
    monkeypatch.setenv("KIS_PAPER_CANDIDATE_POOL_SIZE", "15")
    monkeypatch.setattr(
        repository,
        "get_candidates",
        lambda conn, top_change, top_volume: candidates,
    )
    monkeypatch.setattr(repository, "get_price_history", lambda conn, code: [])
    monkeypatch.setattr(
        "app.ai.kis_autonomous.calculate_stock_analytics",
        lambda history: {
            "technical_bias": {"score": 50},
            "momentum": {"rsi14": 55, "macd_histogram": 1},
        },
    )

    ranked = engine._rank_candidates(conn)

    assert len(ranked) == 15
    assert "368600" not in {item["code"] for item in ranked}
    conn.close()
