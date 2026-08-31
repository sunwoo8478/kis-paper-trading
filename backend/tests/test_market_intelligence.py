from app.market_intelligence import NaverMarketIntelligenceProvider


def test_market_overview_normalizes_indices_and_rankings(monkeypatch):
    provider = NaverMarketIntelligenceProvider()

    def fake_json(path, params=None):
        if path.startswith("/index/"):
            symbol = path.split("/")[2]
            return {"stockName": symbol, "closePrice": "2,500.10", "compareToPreviousClosePrice": "-10.2", "fluctuationsRatio": "-0.41", "marketStatus": "OPEN", "localTradedAt": "2026-08-28T15:30:00+09:00"}
        return {"stocks": [{"itemCode": "005930", "stockName": "삼성전자", "closePriceRaw": "70000", "fluctuationsRatio": "2.5", "marketValueRaw": "1000000", "stockExchangeType": {"nameEng": "KOSPI"}}]}

    monkeypatch.setattr(provider, "_get_json", fake_json)
    result = provider.get_market_overview()

    assert len(result["indices"]) == 2
    assert result["indices"][0]["price"] == 2500.10
    assert result["rankings"]["gainers"][0]["code"] == "005930"


def test_stock_insight_normalizes_fundamentals_and_flows(monkeypatch):
    provider = NaverMarketIntelligenceProvider()

    def fake_json(path, params=None):
        if path.endswith("/basic"):
            return {"stockName": "삼성전자", "closePrice": "70,000", "fluctuationsRatio": "1.2"}
        if path.endswith("/integration"):
            return {
                "totalInfos": [{"code": "per", "key": "PER", "value": "12.3배", "valueDesc": "2026.06."}],
                "dealTrendInfos": [{"bizdate": "20260828", "foreignerPureBuyQuant": "+1,200", "organPureBuyQuant": "-300", "individualPureBuyQuant": "-900"}],
                "consensusInfo": {"recommMean": "4.1", "priceTargetMean": "85,000"},
                "researches": [{"id": 1, "bnm": "테스트증권", "tit": "실적 개선", "wdt": "20260828", "rcnt": "20"}],
            }
        return {"financeInfo": {"trTitleList": [{"key": "202612", "title": "2026.12.", "isConsensus": "Y"}], "rowList": [{"title": "매출액", "columns": {"202612": {"value": "1,000"}}}]}}

    monkeypatch.setattr(provider, "_get_json", fake_json)
    result = provider.get_stock_insight("005930")

    assert result["quote"]["price"] == 70000
    assert result["metrics"]["per"]["value"] == "12.3배"
    assert result["investor_flows"][0]["foreign"] == 1200
    assert result["financials"]["annual"]["metrics"]["매출액"]["202612"] == 1000


def test_realtime_snapshot_normalizes_session_data(monkeypatch):
    provider = NaverMarketIntelligenceProvider()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"datas": [{
                "stockName": "삼성전자",
                "closePriceRaw": "70100",
                "openPriceRaw": "69000",
                "highPriceRaw": "70500",
                "lowPriceRaw": "68800",
                "accumulatedTradingVolumeRaw": "123456",
                "marketValueFullRaw": "1000000000",
                "marketStatus": "OPEN",
                "integratedPriceInfo": {"accumulatedTradingVolumeRaw": "200000"},
                "overMarketPriceInfo": {"tradingSessionType": "REGULAR_MARKET", "overPrice": "70,100"},
            }]}

    monkeypatch.setattr("app.market_intelligence.requests.get", lambda *args, **kwargs: Response())
    result = provider.get_realtime_snapshot("005930")

    assert result["price"] == 70100
    assert result["volume"] == 123456
    assert result["integrated"]["volume"] == 200000
    assert result["after_hours"]["price"] == 70100
