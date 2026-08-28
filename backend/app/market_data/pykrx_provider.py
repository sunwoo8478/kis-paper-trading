from datetime import datetime, timedelta

from pykrx import stock as pykrx_stock

from .base import MarketDataProvider, OhlcvBar, Stock


class PykrxProvider(MarketDataProvider):
    def get_ticker_master(self) -> list[Stock]:
        today = datetime.now().strftime("%Y%m%d")
        result = []
        for market in ("KOSPI", "KOSDAQ"):
            codes = pykrx_stock.get_market_ticker_list(today, market=market)
            for code in codes:
                name = pykrx_stock.get_market_ticker_name(code)
                result.append(Stock(code=code, name=name, market=market))
        return result

    def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
        df = pykrx_stock.get_market_ohlcv(start, end, code)
        bars = []
        for idx, row in df.iterrows():
            bars.append(
                OhlcvBar(
                    date=idx.strftime("%Y-%m-%d"),
                    open=float(row["시가"]),
                    high=float(row["고가"]),
                    low=float(row["저가"]),
                    close=float(row["종가"]),
                    volume=int(row["거래량"]),
                )
            )
        return bars

    def get_latest_price(self, code: str) -> float:
        end = datetime.now()
        start = end - timedelta(days=10)
        bars = self.get_ohlcv(code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        if not bars:
            raise ValueError(f"no price data available for {code}")
        return bars[-1].close
