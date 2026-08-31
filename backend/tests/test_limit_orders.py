import sqlite3

import pytest

from app import repository
from app.execution.simulated_executor import SimulatedExecutor


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    repository.init_db(connection, initial_capital=1_000_000.0)
    yield connection
    connection.close()


class _Provider:
    def __init__(self, price: float):
        self.price = price

    def get_latest_price(self, code: str) -> float:
        return self.price


def test_limit_buy_stays_pending_until_price_crosses(conn):
    provider = _Provider(1000.0)
    executor = SimulatedExecutor(provider, conn)

    result = executor.place_order("005930", "buy", 10, "limit", 900.0)
    assert result.status == "pending"
    assert result.fill_price is None
    assert conn.execute("SELECT status FROM orders WHERE id = ?", (result.order_id,)).fetchone()[0] == "pending"

    provider.price = 890.0
    assert executor.process_pending_orders() == 1
    assert conn.execute("SELECT status, price FROM orders WHERE id = ?", (result.order_id,)).fetchone() == ("filled", 890.0)


def test_pending_order_can_be_cancelled(conn):
    executor = SimulatedExecutor(_Provider(1000.0), conn)
    result = executor.place_order("005930", "buy", 10, "limit", 900.0)
    assert repository.cancel_pending_order(conn, result.order_id) is True
    assert repository.cancel_pending_order(conn, result.order_id) is False


def test_market_fill_rolls_back_when_order_record_fails(conn, monkeypatch):
    executor = SimulatedExecutor(_Provider(1000.0), conn)

    def fail_record(*args, **kwargs):
        raise RuntimeError("database write failed")

    monkeypatch.setattr(repository, "record_order", fail_record)
    with pytest.raises(RuntimeError):
        executor.place_order("005930", "buy", 10)

    assert repository.get_position(conn, "005930") is None
    assert repository.get_cash_balance(conn) == 1_000_000.0
