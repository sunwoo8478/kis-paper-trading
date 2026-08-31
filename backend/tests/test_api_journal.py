from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_trade_journal_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        empty = client.get("/journal/005930").json()
        assert empty["thesis"] == ""
        assert empty["tags"] == []

        response = client.put(
            "/journal/005930",
            json={
                "thesis": "20일 고점 돌파",
                "invalidation": "MA20 종가 이탈",
                "target_price": 1200,
                "tags": ["breakout", "swing"],
            },
        )
        assert response.status_code == 200
        assert response.json()["target_price"] == 1200

        entries = client.get("/journal").json()
        assert entries[0]["code"] == "005930"
        assert entries[0]["tags"] == ["breakout", "swing"]
