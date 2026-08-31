from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import repository
from ..execution.base import OrderExecutionError
from ..portfolio import compute_portfolio_value

router = APIRouter()


class OrderRequest(BaseModel):
    code: str
    side: str
    quantity: int
    order_type: str = "market"
    limit_price: float | None = None


@router.post("/orders")
def create_order(req: OrderRequest, request: Request):
    try:
        result = request.app.state.executor.place_order(
            req.code, req.side, req.quantity, req.order_type, req.limit_price
        )
    except (OrderExecutionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result.status == "filled":
        _record_portfolio_snapshot(request)
    return {
        "order_id": result.order_id,
        "code": result.code,
        "side": result.side,
        "quantity": result.quantity,
        "fill_price": result.fill_price,
        "status": result.status,
        "order_type": result.order_type,
        "limit_price": result.limit_price,
    }


@router.get("/orders")
def list_orders(request: Request):
    if request.app.state.executor.process_pending_orders() > 0:
        _record_portfolio_snapshot(request)
    experiment = repository.get_active_experiment(request.app.state.conn)
    return repository.get_orders(
        request.app.state.conn, experiment["started_at"] if experiment else None
    )


@router.delete("/orders/{order_id}")
def cancel_order(order_id: int, request: Request):
    if not repository.cancel_pending_order(request.app.state.conn, order_id):
        raise HTTPException(status_code=404, detail="pending order not found")
    return {"id": order_id, "status": "cancelled"}


def _record_portfolio_snapshot(request: Request) -> None:
    conn = request.app.state.conn
    provider = request.app.state.provider
    cash = repository.get_cash_balance(conn)
    positions = repository.get_all_positions(conn)
    prices = {}
    for position in positions:
        try:
            prices[position.code] = provider.get_latest_price(position.code)
        except Exception:
            prices[position.code] = position.avg_price
    values = compute_portfolio_value(cash, positions, prices)
    initial_capital = repository.get_initial_capital(conn)
    repository.insert_snapshot(
        conn,
        total_value=values["total_value"],
        cash=values["cash"],
        evaluated_value=values["evaluated_value"],
        pnl=values["total_value"] - initial_capital,
    )
