from fastapi import APIRouter, HTTPException, Query, Request

from ..integrations.kis import KisApiError

router = APIRouter()


@router.get("/kis/status")
def kis_status(request: Request, verify: bool = Query(default=False)):
    return request.app.state.kis_client.status(verify=verify)


@router.get("/kis/quote/{code}")
def kis_quote(code: str, request: Request):
    try:
        return request.app.state.kis_client.get_quote(code.strip().upper())
    except (KisApiError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/kis/balance")
def kis_balance(request: Request):
    try:
        return request.app.state.kis_client.get_balance()
    except KisApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
