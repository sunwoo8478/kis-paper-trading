from fastapi import APIRouter, Request

from .. import repository
from ..portfolio import compute_portfolio_value

router = APIRouter()


@router.get("/portfolio")
def get_portfolio(request: Request):
    conn = request.app.state.conn
    provider = request.app.state.provider
    cash = repository.get_cash_balance(conn)
    positions = repository.get_all_positions(conn)
    current_prices = {}
    for p in positions:
        try:
            current_prices[p.code] = provider.get_latest_price(p.code)
        except Exception:
            current_prices[p.code] = p.avg_price
    value = compute_portfolio_value(cash, positions, current_prices)
    return {
        **value,
        "positions": [
            {"code": p.code, "quantity": p.quantity, "avg_price": p.avg_price} for p in positions
        ],
    }


@router.get("/portfolio/history")
def get_portfolio_history(request: Request):
    return repository.get_snapshots(request.app.state.conn)
