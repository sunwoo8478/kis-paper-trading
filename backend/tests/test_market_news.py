from app.market_news import NaverStockNewsProvider


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return [
            {
                "items": [
                    {
                        "id": "news-1",
                        "officeName": "테스트경제",
                        "datetime": "202608281744",
                        "titleFull": "<b>반도체</b> 실적 개선",
                        "body": "매출이 &amp; 영업이익이 증가했습니다.",
                        "mobileNewsUrl": "https://example.com/news-1",
                    },
                    {"id": "news-1", "title": "중복 기사"},
                ]
            }
        ]


def test_naver_news_provider_normalizes_and_deduplicates(monkeypatch):
    captured = {}

    def fake_get(*args, **kwargs):
        captured.update(kwargs["params"])
        return FakeResponse()

    monkeypatch.setattr("app.market_news.requests.get", fake_get)

    items = NaverStockNewsProvider().get_news("005930", 10, page=3)

    assert captured == {"pageSize": 10, "page": 3}

    assert items == [
        {
            "id": "news-1",
            "code": "005930",
            "source": "테스트경제",
            "published_at": "2026-08-28T17:44:00",
            "title": "반도체 실적 개선",
            "summary": "매출이 & 영업이익이 증가했습니다.",
            "url": "https://example.com/news-1",
            "image_url": None,
        }
    ]
