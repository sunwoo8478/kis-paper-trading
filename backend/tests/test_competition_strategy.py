from app.ai.competition import (
    competition_market_regime,
    competition_target_exposure_pct,
    position_target_pct,
    rank_competition_candidates,
)


def _history(daily_growth: float, volume_growth: int = 0, days: int = 65):
    price = 10_000.0
    bars = []
    for day in range(days):
        price *= 1 + daily_growth
        bars.append({
            "date": f"2026-01-{day + 1:02d}",
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 100_000 + day * volume_growth,
        })
    return bars


def test_competition_ranking_prefers_strong_liquid_momentum():
    items = [
        ({"code": "000001", "name": "강한추세"}, _history(0.012, 5000)),
        ({"code": "000002", "name": "완만한추세"}, _history(0.004, 1000)),
        ({"code": "000003", "name": "하락추세"}, _history(-0.003, 1000)),
    ]

    ranked = rank_competition_candidates(items, min_avg_trading_value=0)

    assert [item["code"] for item in ranked] == ["000001", "000002"]
    assert ranked[0]["score"] > ranked[1]["score"]


def test_competition_ranking_rejects_blowoff_volatility():
    stable = _history(0.005)
    unstable = _history(0.005)
    for index, bar in enumerate(unstable):
        bar["close"] *= 1.4 if index % 2 else 0.7
        bar["open"] = bar["close"]
        bar["high"] = bar["close"] * 1.02
        bar["low"] = bar["close"] * 0.98

    ranked = rank_competition_candidates(
        [
            ({"code": "000001", "name": "안정"}, stable),
            ({"code": "000002", "name": "과열"}, unstable),
        ],
        min_avg_trading_value=0,
        max_volatility_pct=120,
    )

    assert [item["code"] for item in ranked] == ["000001"]


def test_competition_regime_and_drawdown_reduce_exposure():
    bullish = {"above_ma20_ratio": 0.60, "advancing_ratio": 0.58}

    assert competition_market_regime(bullish, 0) == "bullish"
    assert competition_target_exposure_pct("bullish", 0, 0) == 100
    assert competition_target_exposure_pct("bullish", -5.5, 0) == 40
    assert competition_target_exposure_pct("bullish", 0, -2.6) == 0
    assert competition_market_regime(bullish, -8.1) == "risk_off"


def test_position_target_shrinks_for_high_volatility():
    assert position_target_pct(80, 12) < position_target_pct(20, 12)
    assert position_target_pct(80, 12) >= 5
    assert position_target_pct(20, 12) <= 15
