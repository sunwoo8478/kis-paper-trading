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


def test_kis_engine_waits_while_broker_order_has_remaining_quantity(
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "pending.db")
    _seed(db_path)
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
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

    assert result["status"] == "pending_orders"
    assert result["broker_order_ids"] == []
    assert result["blocked_decisions"][0]["rule"] == "open_broker_order"
    assert client.orders == []
    conn = sqlite3.connect(db_path)
    stored = repository.get_kis_paper_orders(conn, 1)[0]
    assert stored["filled_quantity"] == 3
    assert stored["remaining_quantity"] == 7
    conn.close()
