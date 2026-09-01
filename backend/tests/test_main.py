from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_health_check_returns_ok():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["database"] == "connected"
        assert "autonomous" in response.json()
        assert "kis_paper" in response.json()


def test_lifespan_wires_conn_provider_executor(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "500000")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        assert isinstance(client.app.state.provider, PykrxProvider)
        assert client.app.state.executor is not None
        response = client.get("/health")
        assert response.status_code == 200


def test_kis_history_uses_separate_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))

    with TestClient(app) as client:
        response = client.get("/kis/history")

    assert response.status_code == 200
    assert response.json() == []
