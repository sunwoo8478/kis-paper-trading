from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderResult:
    order_id: int
    code: str
    side: str
    quantity: int
    fill_price: float


class OrderExecutionError(Exception):
    pass


class OrderExecutor(ABC):
    @abstractmethod
    def place_order(self, code: str, side: str, quantity: int) -> OrderResult:
        ...
