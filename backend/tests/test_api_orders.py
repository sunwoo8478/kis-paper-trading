from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_create_order_then_list_orders(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "1000000")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.post("/orders", json={"code": "005930", "side": "buy", "quantity": 10})
        assert response.status_code == 200
        assert response.json()["fill_price"] == 1000.0

        response = client.get("/orders")
        assert response.status_code == 200
        assert len(response.json()) == 1


def test_create_order_insufficient_cash_returns_400(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "100")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.post("/orders", json={"code": "005930", "side": "buy", "quantity": 10})
        assert response.status_code == 400


def test_create_order_no_price_data_returns_400(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "1000000")

    def raise_no_price(self, code):
        raise ValueError("no price data available")

    monkeypatch.setattr(PykrxProvider, "get_latest_price", raise_no_price)

    with TestClient(app) as client:
        response = client.post("/orders", json={"code": "005930", "side": "buy", "quantity": 10})
        assert response.status_code == 400
