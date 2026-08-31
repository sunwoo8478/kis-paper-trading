import time
from typing import Any, Callable

import requests

_BASE_URL = "https://m.stock.naver.com/api"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


class NaverMarketIntelligenceProvider:
    """Swappable adapter for Naver's unofficial public mobile stock data."""

    def __init__(self):
        self._cache: dict[str, tuple[float, Any]] = {}

    def get_market_overview(self) -> dict:
        return self._cached("market-overview", 15, self._load_market_overview)

    def get_stock_insight(self, code: str) -> dict:
        return self._cached(f"stock-insight:{code}", 300, lambda: self._load_stock_insight(code))

    def get_realtime_snapshot(self, code: str) -> dict:
        return self._cached(f"realtime:{code}", 3, lambda: self._load_realtime_snapshot(code))

    def _load_market_overview(self) -> dict:
        indices = []
        for symbol in ("KOSPI", "KOSDAQ"):
            try:
                payload = self._get_json(f"/index/{symbol}/basic")
                indices.append({
                    "symbol": symbol,
                    "name": payload.get("stockName") or symbol,
                    "price": _number(payload.get("closePrice")),
                    "change": _number(payload.get("compareToPreviousClosePrice")),
                    "change_pct": _number(payload.get("fluctuationsRatio")),
                    "market_status": payload.get("marketStatus"),
                    "traded_at": payload.get("localTradedAt"),
                })
            except Exception:
                continue

        rankings = {"gainers": [], "losers": [], "market_cap": []}
        endpoints = {"gainers": "up", "losers": "down", "market_cap": "marketValue"}
        for result_key, endpoint in endpoints.items():
            combined = []
            for market in ("KOSPI", "KOSDAQ"):
                try:
                    payload = self._get_json(f"/stocks/{endpoint}/{market}", params={"page": 1, "pageSize": 8})
                    combined.extend(_normalize_ranked_stock(item) for item in payload.get("stocks") or [])
                except Exception:
                    continue
            if result_key == "gainers":
                combined.sort(key=lambda item: item["change_pct"] or 0, reverse=True)
            elif result_key == "losers":
                combined.sort(key=lambda item: item["change_pct"] or 0)
            else:
                combined.sort(key=lambda item: item["market_value"] or 0, reverse=True)
            rankings[result_key] = combined[:8]

        return {"indices": indices, "rankings": rankings, "source": "naver_mobile", "updated_at": _latest_time(indices)}

    def _load_stock_insight(self, code: str) -> dict:
        basic = self._safe_json(f"/stock/{code}/basic")
        integration = self._safe_json(f"/stock/{code}/integration")
        annual = self._safe_json(f"/stock/{code}/finance/annual")
        quarter = self._safe_json(f"/stock/{code}/finance/quarter")
        total_info = {
            item.get("code"): {"label": item.get("key"), "value": item.get("value"), "as_of": item.get("valueDesc")}
            for item in integration.get("totalInfos") or []
            if item.get("code")
        }
        consensus = integration.get("consensusInfo") or {}

        return {
            "code": code,
            "name": basic.get("stockName") or integration.get("stockName") or code,
            "quote": {
                "price": _number(basic.get("closePrice")),
                "change": _number(basic.get("compareToPreviousClosePrice")),
                "change_pct": _number(basic.get("fluctuationsRatio")),
                "market_status": basic.get("marketStatus"),
                "traded_at": basic.get("localTradedAt"),
                "after_hours_price": _number((basic.get("overMarketPriceInfo") or {}).get("overPrice")),
            },
            "metrics": total_info,
            "consensus": {
                "score": _number(consensus.get("recommMean")),
                "target_price": _number(consensus.get("priceTargetMean")),
                "as_of": consensus.get("createDate"),
            },
            "investor_flows": [
                {
                    "date": item.get("bizdate"),
                    "foreign": _number(item.get("foreignerPureBuyQuant")),
                    "institution": _number(item.get("organPureBuyQuant")),
                    "individual": _number(item.get("individualPureBuyQuant")),
                    "foreign_ownership_pct": _number(item.get("foreignerHoldRatio")),
                    "close": _number(item.get("closePrice")),
                }
                for item in integration.get("dealTrendInfos") or []
            ],
            "research": [
                {
                    "id": str(item.get("id")),
                    "broker": item.get("bnm"),
                    "title": item.get("tit"),
                    "date": item.get("wdt"),
                    "views": _number(item.get("rcnt")),
                }
                for item in integration.get("researches") or []
            ],
            "peers": [_normalize_ranked_stock(item) for item in integration.get("industryCompareInfo") or []],
            "company_summary": [
                text for text in (annual.get("corporationSummary") or {}).values() if isinstance(text, str) and text
            ],
            "financials": {
                "annual": _normalize_finance(annual),
                "quarter": _normalize_finance(quarter),
            },
            "source": "naver_mobile",
        }

    def _load_realtime_snapshot(self, code: str) -> dict:
        response = requests.get(
            f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}",
            headers=_HEADERS,
            timeout=5,
        )
        response.raise_for_status()
        rows = response.json().get("datas") or []
        if not rows:
            raise ValueError(f"no realtime data available for {code}")
        item = rows[0]
        integrated = item.get("integratedPriceInfo") or {}
        after_hours = item.get("overMarketPriceInfo") or {}
        return {
            "code": code,
            "name": item.get("stockName") or code,
            "market": (item.get("stockExchangeType") or {}).get("nameEng"),
            "market_status": item.get("marketStatus"),
            "traded_at": item.get("localTradedAt"),
            "price": _number(item.get("closePriceRaw") or item.get("closePrice")),
            "change": _number(item.get("compareToPreviousClosePriceRaw") or item.get("compareToPreviousClosePrice")),
            "change_pct": _number(item.get("fluctuationsRatioRaw") or item.get("fluctuationsRatio")),
            "open": _number(item.get("openPriceRaw") or item.get("openPrice")),
            "high": _number(item.get("highPriceRaw") or item.get("highPrice")),
            "low": _number(item.get("lowPriceRaw") or item.get("lowPrice")),
            "volume": _number(item.get("accumulatedTradingVolumeRaw") or item.get("accumulatedTradingVolume")),
            "trading_value": _number(item.get("accumulatedTradingValueRaw")),
            "market_value": _number(item.get("marketValueFullRaw") or item.get("marketValueFull")),
            "integrated": {
                "open": _number(integrated.get("openPrice")),
                "high": _number(integrated.get("highPrice")),
                "low": _number(integrated.get("lowPrice")),
                "volume": _number(integrated.get("accumulatedTradingVolumeRaw") or integrated.get("accumulatedTradingVolume")),
                "trading_value": _number(integrated.get("accumulatedTradingValueRaw")),
            },
            "after_hours": {
                "session": after_hours.get("tradingSessionType"),
                "status": after_hours.get("overMarketStatus"),
                "price": _number(after_hours.get("overPrice")),
                "change_pct": _number(after_hours.get("fluctuationsRatio")),
                "volume": _number(after_hours.get("accumulatedTradingVolumeRaw") or after_hours.get("accumulatedTradingVolume")),
            },
            "source": "naver_polling",
        }

    def _safe_json(self, path: str) -> dict:
        try:
            value = self._get_json(path)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _get_json(self, path: str, params: dict | None = None):
        response = requests.get(f"{_BASE_URL}{path}", params=params, headers=_HEADERS, timeout=5)
        response.raise_for_status()
        return response.json()

    def _cached(self, key: str, ttl: int, loader: Callable[[], Any]):
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < ttl:
            return cached[1]
        value = loader()
        self._cache[key] = (now, value)
        return value


def _normalize_ranked_stock(item: dict) -> dict:
    exchange = item.get("stockExchangeType") or {}
    return {
        "code": item.get("itemCode"),
        "name": item.get("stockName"),
        "market": exchange.get("nameEng") or exchange.get("name"),
        "price": _number(item.get("closePriceRaw") or item.get("closePrice")),
        "change": _number(item.get("compareToPreviousClosePriceRaw") or item.get("compareToPreviousClosePrice")),
        "change_pct": _number(item.get("fluctuationsRatio")),
        "volume": _number(item.get("accumulatedTradingVolumeRaw") or item.get("accumulatedTradingVolume")),
        "trading_value": _number(item.get("accumulatedTradingValueRaw") or item.get("accumulatedTradingValue")),
        "market_value": _number(item.get("marketValueRaw") or item.get("marketValue")),
    }


def _normalize_finance(payload: dict) -> dict:
    finance = payload.get("financeInfo") or {}
    periods = [
        {"key": item.get("key"), "label": item.get("title"), "consensus": item.get("isConsensus") == "Y"}
        for item in finance.get("trTitleList") or []
    ]
    wanted = {"매출액", "영업이익", "당기순이익", "영업이익률", "순이익률", "ROE", "부채비율", "EPS", "PER", "BPS", "PBR", "주당배당금"}
    metrics = {}
    for row in finance.get("rowList") or []:
        title = row.get("title")
        if title not in wanted:
            continue
        metrics[title] = {
            key: _number((row.get("columns") or {}).get(key, {}).get("value"))
            for key in [period["key"] for period in periods]
            if key
        }
    return {"periods": periods, "metrics": metrics}


def _number(value) -> float | None:
    if value is None or value in ("", "-", "N/A"):
        return None
    try:
        return float(str(value).replace(",", "").replace("+", "").replace("%", ""))
    except ValueError:
        return None


def _latest_time(indices: list[dict]) -> str | None:
    values = [item["traded_at"] for item in indices if item.get("traded_at")]
    return max(values, default=None)
