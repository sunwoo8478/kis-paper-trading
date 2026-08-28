import argparse
import sqlite3
from datetime import datetime, timedelta

from . import repository
from .market_data.base import MarketDataProvider
from .market_data.pykrx_provider import PykrxProvider


def load_all(conn: sqlite3.Connection, provider: MarketDataProvider, lookback_days: int = 90) -> int:
    stocks = provider.get_ticker_master()
    repository.upsert_stocks(conn, stocks)

    end = datetime.now()
    start = end - timedelta(days=lookback_days)

    for stock in stocks:
        try:
            bars = provider.get_ohlcv(stock.code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        except Exception as exc:
            print(f"warning: failed to load {stock.code}: {exc}")
            continue
        if bars:
            repository.upsert_price_history(conn, stock.code, bars)

    return len(stocks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load KOSPI/KOSDAQ market data via pykrx")
    parser.add_argument("--db-path", default="kis_paper_trading.db")
    parser.add_argument("--lookback-days", type=int, default=90)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    repository.init_db(conn)
    count = load_all(conn, PykrxProvider(), args.lookback_days)
    print(f"loaded {count} stocks")


if __name__ == "__main__":
    main()
