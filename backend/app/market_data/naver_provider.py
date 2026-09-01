import requests

from .base import MarketDataProvider, OhlcvBar, Stock
from .pykrx_provider import PykrxProvider

_QUOTE_URL = "https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


class NaverRealtimeProvider(MarketDataProvider):
    """Ticker master and historical OHLCV still come from pykrx (EOD, unaffected).
    Only get_latest_price is overridden to approximate intraday movement via
    Naver Finance's unofficial public polling endpoint. Swap back to
    PykrxProvider, or later to a real KisProvider, by changing
    MARKET_DATA_PROVIDER — no other code depends on this class directly.
    """

    def __init__(self):
        self._pykrx = PykrxProvider()

    def get_ticker_master(self) -> list[Stock]:
        return self._pykrx.get_ticker_master()

    def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
        return self._pykrx.get_ohlcv(code, start, end)

    def get_latest_price(self, code: str) -> float:
        item = self._get_realtime_item(code)
        close_price = item.get("closePrice")
        if not close_price:
            raise ValueError(f"no price data available for {code}")
        return float(close_price.replace(",", ""))

    def get_market_snapshot(self, date: str) -> dict[str, OhlcvBar]:
        return self._pykrx.get_market_snapshot(date)

    def get_market_status(self, code: str = "005930") -> str | None:
        return self._get_realtime_item(code).get("marketStatus")

    @staticmethod
    def _get_realtime_item(code: str) -> dict:
        response = requests.get(_QUOTE_URL.format(code=code), headers=_HEADERS, timeout=5)
        response.raise_for_status()
        payload = response.json()
        datas = payload.get("datas") or []
        if not datas:
            raise ValueError(f"no price data available for {code}")
        return datas[0]
