from fastapi import APIRouter, Query, Request

from .. import repository
from ..market_news import NaverStockNewsProvider

router = APIRouter()
provider = NaverStockNewsProvider()


@router.get("/news")
def market_news(
    request: Request,
    codes: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    page: int = Query(default=1, ge=1, le=100),
):
    selected_codes = _select_codes(request, codes)
    per_stock = max(3, min(10, limit // max(len(selected_codes), 1) + 1))
    items = []
    seen = set()
    for code in selected_codes:
        try:
            stock_items = provider.get_news(code, per_stock, page)
        except Exception:
            continue
        for item in stock_items:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            items.append(item)

    items.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    return items[:limit]


@router.get("/stocks/{code}/news")
def stock_news(
    code: str,
    limit: int = Query(default=10, ge=1, le=30),
    page: int = Query(default=1, ge=1, le=100),
):
    try:
        return provider.get_news(code, limit, page)
    except Exception:
        return []


def _select_codes(request: Request, codes: str) -> list[str]:
    selected = [code.strip() for code in codes.split(",") if code.strip()]
    if not selected:
        selected = [position.code for position in repository.get_all_positions(request.app.state.conn)]
    if not selected:
        selected = [row["code"] for row in repository.get_candidates(request.app.state.conn)]
    return list(dict.fromkeys(selected))[:6]
