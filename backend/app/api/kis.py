from fastapi import APIRouter, HTTPException, Query, Request

from ..integrations.kis import KisApiError
from .. import repository

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


@router.get("/kis/buying-power")
def kis_buying_power(
    request: Request,
    code: str = Query(default="005930"),
    price: float | None = Query(default=None),
):
    try:
        return request.app.state.kis_client.get_buying_power(
            code.strip().upper(),
            price,
        )
    except (KisApiError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/kis/autonomous/status")
def kis_autonomous_status(request: Request):
    return request.app.state.kis_autonomous_engine.status()


@router.post("/kis/autonomous/start")
def kis_autonomous_start(request: Request):
    try:
        request.app.state.kis_autonomous_engine.set_enabled(True)
    except KisApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return request.app.state.kis_autonomous_engine.status()


@router.post("/kis/autonomous/stop")
def kis_autonomous_stop(request: Request):
    request.app.state.kis_autonomous_engine.set_enabled(False)
    return request.app.state.kis_autonomous_engine.status()


@router.post("/kis/autonomous/run")
def kis_autonomous_run(request: Request):
    return request.app.state.kis_autonomous_engine.run_cycle()


@router.get("/kis/autonomous/cycles")
def kis_autonomous_cycles(request: Request, limit: int = Query(default=30)):
    return repository.get_kis_paper_cycles(
        request.app.state.conn,
        max(1, min(limit, 200)),
    )


@router.get("/kis/orders")
def kis_orders(request: Request, limit: int = Query(default=100)):
    return repository.get_kis_paper_orders(
        request.app.state.conn,
        max(1, min(limit, 500)),
    )


@router.get("/kis/history")
def kis_history(request: Request, limit: int = Query(default=1000)):
    return repository.get_kis_paper_snapshots(
        request.app.state.conn,
        max(1, min(limit, 5000)),
    )


@router.get("/kis/broker-orders")
def kis_broker_orders(request: Request):
    try:
        orders = request.app.state.kis_client.get_daily_orders()
    except KisApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    for order in orders:
        repository.reconcile_kis_paper_order(request.app.state.conn, order)
    return orders
