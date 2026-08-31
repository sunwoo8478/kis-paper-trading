from fastapi.testclient import TestClient

from app.api import news
from app.main import app


def test_stock_news_returns_normalized_provider_result(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(
        news.provider,
        "get_news",
        lambda code, limit, page: [{"id": "1", "code": code, "published_at": "2026-08-28T17:44:00", "page": page}],
    )

    with TestClient(app) as client:
        response = client.get("/stocks/005930/news", params={"limit": 5, "page": 4})

    assert response.status_code == 200
    assert response.json()[0]["code"] == "005930"
    assert response.json()[0]["page"] == 4


def test_market_news_tolerates_partial_provider_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))

    def fake_news(code, limit, page):
        if code == "000660":
            raise RuntimeError("temporary upstream error")
        return [{"id": f"item-{code}", "code": code, "published_at": "2026-08-28T17:44:00", "page": page}]

    monkeypatch.setattr(news.provider, "get_news", fake_news)
    with TestClient(app) as client:
        response = client.get("/news", params={"codes": "005930,000660", "limit": 10, "page": 2})

    assert response.status_code == 200
    assert response.json() == [{"id": "item-005930", "code": "005930", "published_at": "2026-08-28T17:44:00", "page": 2}]
