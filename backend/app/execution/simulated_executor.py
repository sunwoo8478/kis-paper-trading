import os

from .. import repository
from ..market_data.base import MarketDataProvider
from .base import OrderExecutionError, OrderExecutor, OrderResult


class SimulatedExecutor(OrderExecutor):
    def __init__(self, provider: MarketDataProvider, conn):
        self.provider = provider
        self.conn = conn

    def place_order(
        self, code: str, side: str, quantity: int, order_type: str = "market", limit_price: float | None = None
    ) -> OrderResult:
        if side not in ("buy", "sell"):
            raise OrderExecutionError(f"invalid side: {side}")
        if quantity <= 0:
            raise OrderExecutionError("quantity must be positive")
        if order_type not in ("market", "limit"):
            raise OrderExecutionError(f"invalid order type: {order_type}")
        if order_type == "limit" and (limit_price is None or limit_price <= 0):
            raise OrderExecutionError("limit price must be positive")

        market_price = self.provider.get_latest_price(code)

        if order_type == "limit" and not self._is_marketable(side, market_price, limit_price):
            self._validate_capacity(code, side, quantity, limit_price)
            order_id = repository.record_order(
                self.conn, code, side, quantity, limit_price, status="pending", order_type="limit", limit_price=limit_price
            )
            return OrderResult(
                order_id=order_id, code=code, side=side, quantity=quantity,
                fill_price=None, status="pending", order_type="limit", limit_price=limit_price,
            )

        cap = self._volume_cap(code)
        fill_quantity = quantity if cap is None else min(quantity, cap)
        price = self._simulated_fill_price(side, market_price)
        if order_type == "limit" and limit_price is not None:
            price = min(price, limit_price) if side == "buy" else max(price, limit_price)
        fill_status = "filled" if fill_quantity == quantity else "partial"
        fill_reason = None if fill_status == "filled" else "거래량 참여율 한도 초과로 부분체결"
        try:
            self._apply_fill(code, side, fill_quantity, price, commit=False)
            order_id = repository.record_order(
                self.conn, code, side, fill_quantity, price,
                status=fill_status, order_type=order_type, limit_price=limit_price,
                requested_quantity=quantity, filled_quantity=fill_quantity,
                fill_reason=fill_reason, commit=False,
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return OrderResult(
            order_id=order_id, code=code, side=side, quantity=quantity,
            fill_price=price, status=fill_status, order_type=order_type, limit_price=limit_price,
            filled_quantity=fill_quantity if fill_status == "partial" else None,
        )

    def process_pending_orders(self) -> int:
        filled = 0
        for order in repository.get_pending_orders(self.conn):
            try:
                market_price = self.provider.get_latest_price(order["code"])
                if not self._is_marketable(order["side"], market_price, order["limit_price"]):
                    continue
                cap = self._volume_cap(order["code"])
                fill_quantity = order["quantity"] if cap is None else min(order["quantity"], cap)
                if fill_quantity <= 0:
                    continue
                price = self._simulated_fill_price(order["side"], market_price)
                price = (
                    min(price, order["limit_price"])
                    if order["side"] == "buy"
                    else max(price, order["limit_price"])
                )
                self._apply_fill(order["code"], order["side"], fill_quantity, price, commit=False)
                fill_status = "filled" if fill_quantity == order["quantity"] else "partial"
                fill_reason = None if fill_status == "filled" else "거래량 참여율 한도 초과로 부분체결"
                repository.fill_pending_order(
                    self.conn, order["id"], price, fill_quantity,
                    status=fill_status, fill_reason=fill_reason,
                )
                filled += 1
            except (OrderExecutionError, ValueError):
                continue
        return filled

    def _volume_cap(self, code: str) -> int | None:
        participation_pct = float(os.getenv("SIMULATED_MAX_VOLUME_PARTICIPATION_PCT", "0"))
        if participation_pct <= 0:
            return None
        avg_volume = repository.get_average_volume(self.conn, code)
        if not avg_volume:
            return None
        cap = int(avg_volume * participation_pct / 100)
        return cap if cap > 0 else None

    def _validate_capacity(self, code: str, side: str, quantity: int, price: float) -> None:
        pending_buy_value, pending_sell_quantities = repository.get_pending_commitments(self.conn)
        if side == "buy":
            cash = repository.get_cash_balance(self.conn)
            cost = price * quantity
            if cost > cash - pending_buy_value:
                raise OrderExecutionError("insufficient cash balance")
        else:
            position = repository.get_position(self.conn, code)
            available = (position.quantity if position else 0) - pending_sell_quantities.get(code, 0)
            if available < quantity:
                raise OrderExecutionError("insufficient position quantity")

    def _apply_fill(self, code: str, side: str, quantity: int, price: float, commit: bool = True) -> None:
        if side == "buy":
            cash = repository.get_cash_balance(self.conn)
            if price * quantity > cash:
                raise OrderExecutionError("insufficient cash balance")
            repository.apply_buy(self.conn, code, quantity, price, commit=commit)
        else:
            position = repository.get_position(self.conn, code)
            if position is None or position.quantity < quantity:
                raise OrderExecutionError("insufficient position quantity")
            repository.apply_sell(self.conn, code, quantity, price, commit=commit)

    @staticmethod
    def _is_marketable(side: str, current_price: float, limit_price: float | None) -> bool:
        if limit_price is None:
            return True
        return current_price <= limit_price if side == "buy" else current_price >= limit_price

    @staticmethod
    def _simulated_fill_price(side: str, market_price: float) -> float:
        slippage_bps = float(os.getenv("SIMULATED_SLIPPAGE_BPS", "0"))
        commission_bps = float(os.getenv("SIMULATED_COMMISSION_BPS", "0"))
        sell_tax_bps = float(os.getenv("SIMULATED_SELL_TAX_BPS", "0")) if side == "sell" else 0
        total_bps = slippage_bps + commission_bps + sell_tax_bps
        multiplier = 1 + total_bps / 10_000 if side == "buy" else 1 - total_bps / 10_000
        return market_price * multiplier
