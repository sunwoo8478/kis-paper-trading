from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    market: str


@dataclass(frozen=True)
class OhlcvBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketDataProvider(ABC):
    @abstractmethod
    def get_ticker_master(self) -> list[Stock]:
        ...

    @abstractmethod
    def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
        ...

    @abstractmethod
    def get_latest_price(self, code: str) -> float:
        ...
