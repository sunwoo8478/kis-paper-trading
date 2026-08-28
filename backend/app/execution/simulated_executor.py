from .. import repository
from ..market_data.base import MarketDataProvider
from .base import OrderExecutionError, OrderExecutor, OrderResult


class SimulatedExecutor(OrderExecutor):
    def __init__(self, provider: MarketDataProvider, conn):
        self.provider = provider
        self.conn = conn

    def place_order(self, code: str, side: str, quantity: int) -> OrderResult:
        if side not in ("buy", "sell"):
            raise OrderExecutionError(f"invalid side: {side}")
        if quantity <= 0:
            raise OrderExecutionError("quantity must be positive")

        price = self.provider.get_latest_price(code)

        if side == "buy":
            cash = repository.get_cash_balance(self.conn)
            cost = price * quantity
            if cost > cash:
                raise OrderExecutionError("insufficient cash balance")
            repository.apply_buy(self.conn, code, quantity, price)
        else:
            position = repository.get_position(self.conn, code)
            if position is None or position.quantity < quantity:
                raise OrderExecutionError("insufficient position quantity")
            repository.apply_sell(self.conn, code, quantity, price)

        order_id = repository.record_order(self.conn, code, side, quantity, price)
        return OrderResult(order_id=order_id, code=code, side=side, quantity=quantity, fill_price=price)
