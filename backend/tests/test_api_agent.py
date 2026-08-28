from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_get_candidates_empty_when_no_price_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.get("/agent/candidates")
        assert response.status_code == 200
        assert response.json() == []


def test_create_and_list_agent_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.post(
            "/agent/runs",
            json={
                "candidates": ["005930"],
                "decisions": [{"code": "005930", "action": "buy", "quantity": 1}],
                "reasoning": "strong momentum",
                "order_ids": [1],
            },
        )
        assert response.status_code == 200
        run_id = response.json()["id"]

        response = client.get("/agent/runs")
        assert response.status_code == 200
        runs = response.json()
        assert runs[0]["id"] == run_id
        assert runs[0]["candidates"] == ["005930"]
        assert runs[0]["decisions"] == [{"code": "005930", "action": "buy", "quantity": 1}]
        assert runs[0]["reasoning"] == "strong momentum"
        assert runs[0]["order_ids"] == [1]
