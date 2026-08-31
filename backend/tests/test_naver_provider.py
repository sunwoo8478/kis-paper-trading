import pytest

from app.market_data.naver_provider import NaverRealtimeProvider
from app.market_data.pykrx_provider import PykrxProvider


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_get_latest_price_parses_comma_formatted_close_price(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.naver_provider.requests.get",
        lambda url, headers, timeout: _FakeResponse(
            {"datas": [{"closePrice": "257,000"}]}
        ),
    )

    provider = NaverRealtimeProvider()
    assert provider.get_latest_price("005930") == 257000.0


def test_get_latest_price_raises_when_no_data(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.naver_provider.requests.get",
        lambda url, headers, timeout: _FakeResponse({"datas": []}),
    )

    provider = NaverRealtimeProvider()
    with pytest.raises(ValueError):
        provider.get_latest_price("005930")


def test_get_ticker_master_and_ohlcv_delegate_to_pykrx(monkeypatch):
    sentinel_stocks = ["stock-sentinel"]
    sentinel_bars = ["bar-sentinel"]
    monkeypatch.setattr(PykrxProvider, "get_ticker_master", lambda self: sentinel_stocks)
    monkeypatch.setattr(
        PykrxProvider, "get_ohlcv", lambda self, code, start, end: sentinel_bars
    )

    provider = NaverRealtimeProvider()
    assert provider.get_ticker_master() is sentinel_stocks
    assert provider.get_ohlcv("005930", "20260101", "20260201") is sentinel_bars
