from fastapi import APIRouter, HTTPException, Query, Request

from .. import repository

router = APIRouter()


@router.get("/stocks")
def search_stocks(request: Request, q: str = Query(default="")):
    return repository.search_stocks(request.app.state.conn, q)


@router.get("/stocks/{code}/history")
def stock_history(code: str, request: Request):
    return repository.get_price_history(request.app.state.conn, code)


@router.get("/stocks/{code}/quote")
def stock_quote(code: str, request: Request):
    try:
        price = request.app.state.provider.get_latest_price(code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"code": code, "price": price}
