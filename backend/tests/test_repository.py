import sqlite3

import pytest

from app import repository


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    repository.init_db(connection, initial_capital=1_000_000.0)
    yield connection
    connection.close()


def test_init_db_sets_initial_cash_balance(conn):
    assert repository.get_cash_balance(conn) == 1_000_000.0


def test_apply_buy_creates_position_and_deducts_cash(conn):
    repository.apply_buy(conn, "005930", 10, 70000.0)
    position = repository.get_position(conn, "005930")
    assert position.quantity == 10
    assert position.avg_price == 70000.0
    assert repository.get_cash_balance(conn) == 300_000.0


def test_apply_buy_twice_averages_position(conn):
    repository.apply_buy(conn, "005930", 10, 70000.0)
    repository.apply_buy(conn, "005930", 10, 72000.0)
    position = repository.get_position(conn, "005930")
    assert position.quantity == 20
    assert position.avg_price == pytest.approx(71000.0)


def test_apply_sell_returns_realized_pnl_and_credits_cash(conn):
    repository.apply_buy(conn, "005930", 10, 70000.0)
    realized_pnl = repository.apply_sell(conn, "005930", 10, 75000.0)
    assert realized_pnl == pytest.approx(50_000.0)
    assert repository.get_position(conn, "005930") is None
    assert repository.get_cash_balance(conn) == pytest.approx(1_050_000.0)


def test_apply_sell_without_position_raises(conn):
    with pytest.raises(ValueError):
        repository.apply_sell(conn, "005930", 1, 70000.0)


def test_record_order_and_get_orders(conn):
    order_id = repository.record_order(conn, "005930", "buy", 10, 70000.0)
    orders = repository.get_orders(conn)
    assert orders[0]["id"] == order_id
    assert orders[0]["code"] == "005930"
    assert orders[0]["side"] == "buy"
    assert orders[0]["status"] == "filled"


def test_insert_snapshot_and_get_snapshots(conn):
    repository.insert_snapshot(conn, total_value=1_000_000.0, cash=1_000_000.0, evaluated_value=0.0, pnl=0.0)
    snapshots = repository.get_snapshots(conn)
    assert len(snapshots) == 1
    assert snapshots[0]["total_value"] == 1_000_000.0


from dataclasses import dataclass


@dataclass
class _FakeStock:
    code: str
    name: str
    market: str


@dataclass
class _FakeBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def test_upsert_and_search_stocks(conn):
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="삼성전자", market="KOSPI")])
    results = repository.search_stocks(conn, "삼성")
    assert results == [
        {
            "code": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "last_price": None,
            "prev_close": None,
            "change_pct": None,
        }
    ]


def test_search_stocks_computes_change_pct_from_price_history(conn):
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="삼성전자", market="KOSPI")])
    repository.upsert_price_history(
        conn,
        "005930",
        [
            _FakeBar(date="2026-08-26", open=69000, high=70500, low=68500, close=70000, volume=900_000),
            _FakeBar(date="2026-08-27", open=70000, high=71000, low=69500, close=70700, volume=1_000_000),
        ],
    )
    results = repository.search_stocks(conn, "005930")
    assert results[0]["last_price"] == 70700
    assert results[0]["prev_close"] == 70000
    assert results[0]["change_pct"] == pytest.approx(1.0)


def test_upsert_stocks_updates_existing_row(conn):
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="old", market="KOSPI")])
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="삼성전자", market="KOSPI")])
    results = repository.search_stocks(conn, "005930")
    assert results[0]["code"] == "005930"
    assert results[0]["name"] == "삼성전자"
    assert results[0]["market"] == "KOSPI"


def test_upsert_and_get_price_history(conn):
    bar = _FakeBar(date="2026-08-27", open=70000, high=71000, low=69500, close=70500, volume=1_000_000)
    repository.upsert_price_history(conn, "005930", [bar])
    history = repository.get_price_history(conn, "005930")
    assert history == [
        {"date": "2026-08-27", "open": 70000, "high": 71000, "low": 69500, "close": 70500, "volume": 1_000_000}
    ]


def test_watchlist_add_remove_and_list(conn):
    repository.upsert_stocks(
        conn,
        [
            _FakeStock(code="005930", name="삼성전자", market="KOSPI"),
            _FakeStock(code="000660", name="SK하이닉스", market="KOSPI"),
        ],
    )
    repository.add_watchlist(conn, "005930")
    repository.add_watchlist(conn, "000660")
    assert [w["code"] for w in repository.get_watchlist(conn)] == ["000660", "005930"]
    repository.remove_watchlist(conn, "000660")
    assert [w["code"] for w in repository.get_watchlist(conn)] == ["005930"]
