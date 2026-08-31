import html
import re
from datetime import datetime

import requests

_NEWS_URL = "https://m.stock.naver.com/api/news/stock/{code}"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TAG_PATTERN = re.compile(r"<[^>]+>")


class NaverStockNewsProvider:
    """Small, swappable adapter around Naver's unofficial mobile stock feed."""

    def get_news(self, code: str, limit: int = 10, page: int = 1) -> list[dict]:
        response = requests.get(
            _NEWS_URL.format(code=code),
            params={"pageSize": limit, "page": page},
            headers=_HEADERS,
            timeout=5,
        )
        response.raise_for_status()
        groups = response.json()
        if not isinstance(groups, list):
            return []

        results = []
        seen = set()
        for group in groups:
            if not isinstance(group, dict):
                continue
            for item in group.get("items") or []:
                if not isinstance(item, dict):
                    continue
                news_id = str(item.get("id") or f"{item.get('officeId', '')}:{item.get('articleId', '')}")
                if not news_id or news_id in seen:
                    continue
                seen.add(news_id)
                results.append({
                    "id": news_id,
                    "code": code,
                    "source": item.get("officeName") or "네이버 증권",
                    "published_at": _parse_datetime(item.get("datetime")),
                    "title": _clean_text(item.get("titleFull") or item.get("title") or ""),
                    "summary": _clean_text(item.get("body") or ""),
                    "url": item.get("mobileNewsUrl") or "",
                    "image_url": item.get("imageOriginLink") or None,
                })
                if len(results) >= limit:
                    return results
        return results


def _clean_text(value: str) -> str:
    return " ".join(html.unescape(_TAG_PATTERN.sub(" ", value)).split())


def _parse_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d%H%M").isoformat()
    except ValueError:
        return value
