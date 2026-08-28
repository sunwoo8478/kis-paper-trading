from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_portfolio_reflects_filled_order(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "1000000")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        client.post("/orders", json={"code": "005930", "side": "buy", "quantity": 10})

        response = client.get("/portfolio")
        assert response.status_code == 200
        body = response.json()
        assert body["cash"] == 990_000.0
        assert body["evaluated_value"] == 10_000.0
        assert body["positions"] == [{"code": "005930", "quantity": 10, "avg_price": 1000.0}]


def test_portfolio_history_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.get("/portfolio/history")
        assert response.status_code == 200
        assert response.json() == []
