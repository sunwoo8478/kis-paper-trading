import pandas as pd
import pytest

from app.market_data.pykrx_provider import PykrxProvider


def test_get_ticker_master_returns_stocks_from_both_markets(monkeypatch):
    def fake_get_market_ticker_list(date, market):
        return {"KOSPI": ["005930"], "KOSDAQ": ["247540"]}[market]

    def fake_get_market_ticker_name(code):
        return {"005930": "삼성전자", "247540": "에코프로비엠"}[code]

    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ticker_list",
        fake_get_market_ticker_list,
    )
    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ticker_name",
        fake_get_market_ticker_name,
    )

    provider = PykrxProvider()
    stocks = provider.get_ticker_master()

    assert {(s.code, s.name, s.market) for s in stocks} == {
        ("005930", "삼성전자", "KOSPI"),
        ("247540", "에코프로비엠", "KOSDAQ"),
    }


def test_get_ohlcv_maps_korean_columns_to_ohlcv_bar(monkeypatch):
    df = pd.DataFrame(
        {"시가": [70000], "고가": [71000], "저가": [69500], "종가": [70500], "거래량": [1_000_000]},
        index=pd.to_datetime(["2026-08-27"]),
    )

    def fake_get_market_ohlcv(start, end, code):
        return df

    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ohlcv",
        fake_get_market_ohlcv,
    )

    provider = PykrxProvider()
    bars = provider.get_ohlcv("005930", "20260801", "20260827")

    assert len(bars) == 1
    assert bars[0].date == "2026-08-27"
    assert bars[0].close == 70500.0
    assert bars[0].volume == 1_000_000


def test_get_latest_price_returns_most_recent_close(monkeypatch):
    df = pd.DataFrame(
        {"시가": [70000, 71000], "고가": [71000, 72000], "저가": [69500, 70500],
         "종가": [70500, 71500], "거래량": [1_000_000, 900_000]},
        index=pd.to_datetime(["2026-08-26", "2026-08-27"]),
    )

    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ohlcv",
        lambda start, end, code: df,
    )

    provider = PykrxProvider()
    assert provider.get_latest_price("005930") == 71500.0


def test_get_latest_price_raises_when_no_data(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ohlcv",
        lambda start, end, code: pd.DataFrame(),
    )

    provider = PykrxProvider()
    with pytest.raises(ValueError):
        provider.get_latest_price("005930")
