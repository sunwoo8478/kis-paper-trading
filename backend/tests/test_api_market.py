from fastapi.testclient import TestClient

from app.api import market
from app.main import app


def test_market_api_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(market.provider, "get_market_overview", lambda: {"indices": [], "rankings": {}})
    monkeypatch.setattr(market.provider, "get_stock_insight", lambda code: {"code": code})
    monkeypatch.setattr(market.provider, "get_realtime_snapshot", lambda code: {"code": code, "price": 70000})

    with TestClient(app) as client:
        overview = client.get("/market/overview")
        insight = client.get("/stocks/005930/insight")
        realtime = client.get("/stocks/005930/realtime")

    assert overview.status_code == 200
    assert overview.json()["indices"] == []
    assert insight.json() == {"code": "005930"}
    assert realtime.json()["price"] == 70000
