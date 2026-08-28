from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    code: str
    quantity: int
    avg_price: float


def apply_buy_fill(
    existing: Position | None, code: str, quantity: int, price: float
) -> Position:
    if existing is None:
        return Position(code=code, quantity=quantity, avg_price=price)
    total_cost = existing.avg_price * existing.quantity + price * quantity
    total_quantity = existing.quantity + quantity
    return Position(code=code, quantity=total_quantity, avg_price=total_cost / total_quantity)


def apply_sell_fill(
    existing: Position, quantity: int, price: float
) -> tuple[Position | None, float]:
    if quantity > existing.quantity:
        raise ValueError("cannot sell more than held quantity")
    realized_pnl = (price - existing.avg_price) * quantity
    remaining = existing.quantity - quantity
    if remaining == 0:
        return None, realized_pnl
    return Position(code=existing.code, quantity=remaining, avg_price=existing.avg_price), realized_pnl


def compute_portfolio_value(
    cash: float, positions: list[Position], current_prices: dict[str, float]
) -> dict:
    evaluated_value = sum(current_prices[p.code] * p.quantity for p in positions)
    cost_basis = sum(p.avg_price * p.quantity for p in positions)
    return {
        "cash": cash,
        "evaluated_value": evaluated_value,
        "total_value": cash + evaluated_value,
        "unrealized_pnl": evaluated_value - cost_basis,
    }
