from fastapi import APIRouter, Query, Request

from .. import repository

router = APIRouter()


@router.get("/stocks")
def search_stocks(request: Request, q: str = Query(default="")):
    return repository.search_stocks(request.app.state.conn, q)


@router.get("/stocks/{code}/history")
def stock_history(code: str, request: Request):
    return repository.get_price_history(request.app.state.conn, code)
