from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .. import repository

router = APIRouter()


class PriceAlertRequest(BaseModel):
    code: str
    direction: str
    target_price: float


@router.get("/alerts")
def list_alerts(request: Request, code: str | None = Query(default=None)):
    conn = request.app.state.conn
    provider = request.app.state.provider
    alerts = repository.get_price_alerts(conn, code)
    for alert in alerts:
        if not alert["active"]:
            continue
        try:
            price = provider.get_latest_price(alert["code"])
        except Exception:
            continue
        reached = price >= alert["target_price"] if alert["direction"] == "above" else price <= alert["target_price"]
        if reached:
            repository.trigger_price_alert(conn, alert["id"])
    return repository.get_price_alerts(conn, code)


@router.post("/alerts")
def create_alert(req: PriceAlertRequest, request: Request):
    if req.direction not in ("above", "below"):
        raise HTTPException(status_code=400, detail="direction must be above or below")
    if req.target_price <= 0:
        raise HTTPException(status_code=400, detail="target price must be positive")
    alert_id = repository.create_price_alert(
        request.app.state.conn, req.code, req.direction, req.target_price
    )
    return {"id": alert_id, **req.model_dump(), "active": True}


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int, request: Request):
    if not repository.delete_price_alert(request.app.state.conn, alert_id):
        raise HTTPException(status_code=404, detail="alert not found")
    return {"id": alert_id}
