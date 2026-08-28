import sqlite3

import pytest

from app import repository
from app.execution.base import OrderExecutionError
from app.execution.simulated_executor import SimulatedExecutor


class _FakeProvider:
    def __init__(self, price: float):
        self.price = price

    def get_latest_price(self, code: str) -> float:
        return self.price


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    repository.init_db(connection, initial_capital=1_000_000.0)
    yield connection
    connection.close()


def test_place_buy_order_fills_at_latest_price(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    result = executor.place_order("005930", "buy", 10)

    assert result.fill_price == 70000.0
    assert result.side == "buy"
    position = repository.get_position(conn, "005930")
    assert position.quantity == 10
    assert repository.get_cash_balance(conn) == 300_000.0


def test_place_sell_order_without_position_raises(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    with pytest.raises(OrderExecutionError):
        executor.place_order("005930", "sell", 1)


def test_place_buy_order_exceeding_cash_raises(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    with pytest.raises(OrderExecutionError):
        executor.place_order("005930", "buy", 1000)


def test_place_order_rejects_invalid_side(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    with pytest.raises(OrderExecutionError):
        executor.place_order("005930", "hold", 1)


def test_place_order_rejects_non_positive_quantity(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    with pytest.raises(OrderExecutionError):
        executor.place_order("005930", "buy", 0)


def test_place_sell_order_records_order_history(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    executor.place_order("005930", "buy", 10)
    executor.place_order("005930", "sell", 4)

    orders = repository.get_orders(conn)
    assert len(orders) == 2
    assert orders[0]["side"] == "sell"
    assert orders[0]["quantity"] == 4
