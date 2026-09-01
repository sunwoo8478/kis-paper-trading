import math
import statistics


def rank_competition_candidates(
    items: list[tuple[dict, list[dict]]],
    pool_size: int = 30,
    min_avg_trading_value: float = 1_000_000_000,
    min_price: float = 1_000,
    max_return_20_pct: float = 120,
    max_volatility_pct: float = 120,
) -> list[dict]:
    """Rank liquid Korean stocks for a roughly three-month momentum contest."""
    measured = []
    for candidate, history in items:
        metrics = _measure(history)
        if metrics is None:
            continue
        if metrics["close"] < min_price:
            continue
        if metrics["avg_trading_value_20"] < min_avg_trading_value:
            continue
        if metrics["return_20_pct"] <= 0 or metrics["close"] <= metrics["ma20"]:
            continue
        if metrics["return_20_pct"] > max_return_20_pct:
            continue
        if metrics["volatility_pct"] > max_volatility_pct:
            continue
        measured.append({**candidate, **metrics})

    if not measured:
        return []

    factors = {
        "return_5_pct": 20,
        "return_20_pct": 30,
        "return_60_pct": 15,
        "risk_adjusted_momentum": 15,
        "volume_ratio_20": 10,
        "breakout_ratio_20": 10,
    }
    percentiles = {
        name: _percentile_map(measured, name)
        for name in factors
    }
    ranked = []
    for item in measured:
        score = sum(
            weight * percentiles[name][item["code"]]
            for name, weight in factors.items()
        )
        trend_bonus = 5 if item["ma60"] and item["ma20"] > item["ma60"] else 0
        ranked.append({**item, "score": round(min(100.0, score + trend_bonus), 2)})
    ranked.sort(
        key=lambda item: (
            item["score"],
            item["avg_trading_value_20"],
        ),
        reverse=True,
    )
    return ranked[:max(1, pool_size)]


def competition_market_regime(
    breadth: dict,
    max_drawdown_pct: float,
    max_drawdown_stop_pct: float = 8.0,
) -> str:
    if max_drawdown_pct <= -max_drawdown_stop_pct:
        return "risk_off"
    above_ma20 = float(breadth.get("above_ma20_ratio") or 0)
    advancing = float(breadth.get("advancing_ratio") or 0)
    if above_ma20 >= 0.55 and advancing >= 0.45:
        return "bullish"
    if above_ma20 >= 0.45 and advancing >= 0.38:
        return "neutral"
    return "bearish"


def competition_target_exposure_pct(
    market_regime: str,
    max_drawdown_pct: float,
    daily_return_pct: float | None,
    daily_stop_pct: float = 2.5,
    max_drawdown_stop_pct: float = 8.0,
) -> float:
    if daily_return_pct is not None and daily_return_pct <= -daily_stop_pct:
        return 0.0
    target = {
        "bullish": 100.0,
        "neutral": 75.0,
        "bearish": 30.0,
        "risk_off": 0.0,
    }.get(market_regime, 30.0)
    if max_drawdown_pct <= -max_drawdown_stop_pct:
        return 0.0
    if max_drawdown_pct <= -5:
        return min(target, 40.0)
    if max_drawdown_pct <= -3:
        return min(target, 70.0)
    return target


def position_target_pct(volatility_pct: float | None, base_pct: float = 12.0) -> float:
    if not volatility_pct or volatility_pct <= 0:
        return base_pct
    scale = max(0.5, min(1.25, 35.0 / volatility_pct))
    return max(5.0, min(15.0, base_pct * scale))


def _measure(history: list[dict]) -> dict | None:
    if len(history) < 21:
        return None
    closes = [float(bar["close"]) for bar in history if float(bar["close"]) > 0]
    if len(closes) < 21:
        return None
    volumes = [max(0, int(bar["volume"])) for bar in history[-len(closes):]]
    close = closes[-1]

    def period_return(period: int) -> float:
        available = min(period, len(closes) - 1)
        base = closes[-available - 1]
        return (close / base - 1) * 100 if base > 0 else 0.0

    returns = [
        math.log(current / previous)
        for previous, current in zip(closes[-21:-1], closes[-20:])
        if previous > 0 and current > 0
    ]
    volatility = statistics.stdev(returns) * math.sqrt(252) * 100 if len(returns) >= 2 else 0.0
    avg_volume = sum(volumes[-20:]) / min(20, len(volumes))
    avg_trading_value = sum(
        price * volume for price, volume in zip(closes[-20:], volumes[-20:])
    ) / min(20, len(closes))
    return_20 = period_return(20)
    high_20 = max(closes[-20:])
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
    return {
        "close": close,
        "ma20": ma20,
        "ma60": ma60,
        "return_5_pct": period_return(5),
        "return_20_pct": return_20,
        "return_60_pct": period_return(60),
        "risk_adjusted_momentum": return_20 / max(volatility, 10.0),
        "volume_ratio_20": volumes[-1] / avg_volume if avg_volume else 0.0,
        "breakout_ratio_20": close / high_20 if high_20 else 0.0,
        "avg_trading_value_20": avg_trading_value,
        "volatility_pct": volatility,
    }


def _percentile_map(items: list[dict], field: str) -> dict[str, float]:
    ordered = sorted(items, key=lambda item: float(item.get(field) or 0))
    denominator = max(1, len(ordered) - 1)
    return {
        item["code"]: index / denominator
        for index, item in enumerate(ordered)
    }
