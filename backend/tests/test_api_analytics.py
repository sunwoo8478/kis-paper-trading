from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app import repository
from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


@dataclass
class _Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def test_stock_analytics_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 120.0)

    with TestClient(app) as client:
        repository.upsert_price_history(
            app.state.conn,
            "005930",
            [_Bar(f"2026-08-{index + 1:02d}", 100 + index, 102 + index, 99 + index, 101 + index, 1000 + index) for index in range(20)],
        )
        response = client.get("/stocks/005930/analytics")
        assert response.status_code == 200
        assert response.json()["moving_averages"]["ma20"] == pytest.approx(110.5)


def test_portfolio_risk_endpoint_enriches_positions(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "1000000")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1200.0)

    with TestClient(app) as client:
        client.post("/orders", json={"code": "005930", "side": "buy", "quantity": 100})
        response = client.get("/portfolio/risk")
        assert response.status_code == 200
        body = response.json()
        assert body["positions"][0]["current_price"] == 1200.0
        assert body["positions"][0]["weight_pct"] == 100.0
        assert body["cash_ratio_pct"] == pytest.approx(88.0)
        assert body["max_position_weight_pct"] == 100.0
        assert body["risk_flags"][0]["code"] == "concentration"
