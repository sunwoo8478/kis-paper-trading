from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_create_trigger_and_delete_price_alert(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    price = {"value": 1000.0}
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: price["value"])

    with TestClient(app) as client:
        response = client.post("/alerts", json={"code": "005930", "direction": "above", "target_price": 1100})
        assert response.status_code == 200
        alert_id = response.json()["id"]

        assert client.get("/alerts?code=005930").json()[0]["active"] is True
        price["value"] = 1200.0
        assert client.get("/alerts?code=005930").json()[0]["active"] is False

        response = client.delete(f"/alerts/{alert_id}")
        assert response.status_code == 200
        assert client.get("/alerts?code=005930").json() == []
