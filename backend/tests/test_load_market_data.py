import sqlite3

from app import repository
from app.load_market_data import load_all
from app.market_data.base import OhlcvBar, Stock


class _FakeProvider:
    def get_ticker_master(self) -> list[Stock]:
        return [Stock(code="005930", name="삼성전자", market="KOSPI")]

    def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
        return [
            OhlcvBar(date="2026-08-27", open=70000, high=71000, low=69500, close=70500, volume=1_000_000)
        ]

    def get_latest_price(self, code: str) -> float:
        return 70500.0


def test_load_all_inserts_stocks_and_price_history():
    conn = sqlite3.connect(":memory:")
    repository.init_db(conn)

    count = load_all(conn, _FakeProvider())

    assert count == 1
    stocks = repository.search_stocks(conn, "005930")
    assert stocks == [
        {
            "code": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "last_price": 70500,
            "prev_close": None,
            "change_pct": None,
        }
    ]
    history = repository.get_price_history(conn, "005930")
    assert len(history) == 1
    assert history[0]["close"] == 70500


def test_load_all_skips_stocks_with_no_bars():
    class _EmptyBarsProvider(_FakeProvider):
        def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
            return []

    conn = sqlite3.connect(":memory:")
    repository.init_db(conn)

    count = load_all(conn, _EmptyBarsProvider())

    assert count == 1
    assert repository.get_price_history(conn, "005930") == []


def test_load_all_continues_after_one_stock_fails():
    class _PartialFailProvider:
        def get_ticker_master(self) -> list[Stock]:
            return [
                Stock(code="005930", name="삼성전자", market="KOSPI"),
                Stock(code="000660", name="SK하이닉스", market="KOSPI"),
            ]

        def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
            if code == "005930":
                raise RuntimeError("network error")
            return [
                OhlcvBar(date="2026-08-27", open=100, high=110, low=95, close=105, volume=500_000)
            ]

        def get_latest_price(self, code: str) -> float:
            return 105.0

    conn = sqlite3.connect(":memory:")
    repository.init_db(conn)

    count = load_all(conn, _PartialFailProvider())

    assert count == 2
    assert repository.get_price_history(conn, "005930") == []
    history = repository.get_price_history(conn, "000660")
    assert len(history) == 1
    assert history[0]["close"] == 105
