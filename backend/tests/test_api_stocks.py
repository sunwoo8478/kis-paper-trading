from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_search_stocks_and_get_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.get("/stocks", params={"q": "005930"})
        assert response.status_code == 200
        assert response.json() == []

        response = client.get("/stocks/005930/history")
        assert response.status_code == 200
        assert response.json() == []
