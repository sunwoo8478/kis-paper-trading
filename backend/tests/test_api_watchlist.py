from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_watchlist_add_list_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.post("/watchlist", json={"code": "005930"})
        assert response.status_code == 200

        response = client.get("/watchlist")
        assert response.status_code == 200
        assert response.json() == ["005930"]

        response = client.delete("/watchlist/005930")
        assert response.status_code == 200

        response = client.get("/watchlist")
        assert response.json() == []
