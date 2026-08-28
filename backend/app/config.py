import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str
    initial_capital: float
    market_data_provider: str
    order_executor: str


def load_settings() -> Settings:
    return Settings(
        db_path=os.environ.get("DB_PATH", "kis_paper_trading.db"),
        initial_capital=float(os.environ.get("INITIAL_CAPITAL", "10000000")),
        market_data_provider=os.environ.get("MARKET_DATA_PROVIDER", "pykrx"),
        order_executor=os.environ.get("ORDER_EXECUTOR", "simulated"),
    )
