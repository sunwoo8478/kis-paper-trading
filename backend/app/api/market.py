from fastapi import APIRouter

from ..market_intelligence import NaverMarketIntelligenceProvider

router = APIRouter()
provider = NaverMarketIntelligenceProvider()


@router.get("/market/overview")
def market_overview():
    return provider.get_market_overview()


@router.get("/stocks/{code}/insight")
def stock_insight(code: str):
    return provider.get_stock_insight(code)


@router.get("/stocks/{code}/realtime")
def stock_realtime(code: str):
    return provider.get_realtime_snapshot(code)
