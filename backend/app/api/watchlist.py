from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import repository

router = APIRouter()


class WatchlistRequest(BaseModel):
    code: str


@router.get("/watchlist")
def list_watchlist(request: Request):
    return repository.get_watchlist(request.app.state.conn)


@router.post("/watchlist")
def add_watchlist(req: WatchlistRequest, request: Request):
    repository.add_watchlist(request.app.state.conn, req.code)
    return {"code": req.code}


@router.delete("/watchlist/{code}")
def remove_watchlist(code: str, request: Request):
    repository.remove_watchlist(request.app.state.conn, code)
    return {"code": code}
