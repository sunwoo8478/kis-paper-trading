from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import repository
from ..execution.base import OrderExecutionError

router = APIRouter()


class OrderRequest(BaseModel):
    code: str
    side: str
    quantity: int


@router.post("/orders")
def create_order(req: OrderRequest, request: Request):
    try:
        result = request.app.state.executor.place_order(req.code, req.side, req.quantity)
    except OrderExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "order_id": result.order_id,
        "code": result.code,
        "side": result.side,
        "quantity": result.quantity,
        "fill_price": result.fill_price,
    }


@router.get("/orders")
def list_orders(request: Request):
    return repository.get_orders(request.app.state.conn)
