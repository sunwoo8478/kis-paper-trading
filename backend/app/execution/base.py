from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderResult:
    order_id: int
    code: str
    side: str
    quantity: int
    fill_price: float | None
    status: str = "filled"
    order_type: str = "market"
    limit_price: float | None = None
    broker_order_id: str | None = None


class OrderExecutionError(Exception):
    pass


class OrderExecutor(ABC):
    @abstractmethod
    def place_order(
        self, code: str, side: str, quantity: int, order_type: str = "market", limit_price: float | None = None
    ) -> OrderResult:
        ...
