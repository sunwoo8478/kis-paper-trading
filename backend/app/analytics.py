import math
import statistics


def calculate_stock_analytics(history: list[dict]) -> dict:
    if not history:
        return _empty_analytics()

    closes = [float(bar["close"]) for bar in history]
    volumes = [int(bar["volume"]) for bar in history]
    latest = history[-1]
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)
    ma120 = _sma(closes, 120)
    rsi14 = _rsi(closes, 14)
    macd, macd_signal, macd_histogram = _macd(closes)
    atr14 = _atr(history, 14)
    volatility = _annualized_volatility(closes)
    bollinger = _bollinger(closes, 20)
    recent_20 = history[-20:]
    recent_252 = history[-252:]
    average_volume_20 = sum(volumes[-20:]) / min(20, len(volumes))
    volume_ratio = volumes[-1] / average_volume_20 if average_volume_20 else None

    score = 0
    if ma20 is not None:
        score += 20 if closes[-1] > ma20 else -20
    if ma20 is not None and ma60 is not None:
        score += 25 if ma20 > ma60 else -25
    if macd_histogram is not None:
        score += 20 if macd_histogram > 0 else -20
    if rsi14 is not None:
        if 45 <= rsi14 <= 65:
            score += 10
        elif rsi14 >= 75:
            score -= 10
        elif rsi14 <= 25:
            score += 5
    score = max(-100, min(100, score))

    return {
        "as_of": latest["date"],
        "close": closes[-1],
        "day": {
            "open": latest["open"],
            "high": latest["high"],
            "low": latest["low"],
            "volume": latest["volume"],
        },
        "moving_averages": {"ma5": ma5, "ma20": ma20, "ma60": ma60, "ma120": ma120},
        "momentum": {
            "rsi14": rsi14,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_histogram": macd_histogram,
        },
        "volatility": {
            "annualized_pct": volatility,
            "atr14": atr14,
            "bollinger_upper": bollinger[0],
            "bollinger_middle": bollinger[1],
            "bollinger_lower": bollinger[2],
        },
        "volume": {"average_20": average_volume_20, "ratio_20": volume_ratio},
        "ranges": {
            "high_20": max(float(bar["high"]) for bar in recent_20),
            "low_20": min(float(bar["low"]) for bar in recent_20),
            "high_52w": max(float(bar["high"]) for bar in recent_252),
            "low_52w": min(float(bar["low"]) for bar in recent_252),
        },
        "technical_bias": {
            "score": score,
            "label": "bullish" if score >= 25 else "bearish" if score <= -25 else "neutral",
        },
    }


def _empty_analytics() -> dict:
    return {
        "as_of": None,
        "close": None,
        "day": {"open": None, "high": None, "low": None, "volume": None},
        "moving_averages": {"ma5": None, "ma20": None, "ma60": None, "ma120": None},
        "momentum": {"rsi14": None, "macd": None, "macd_signal": None, "macd_histogram": None},
        "volatility": {"annualized_pct": None, "atr14": None, "bollinger_upper": None, "bollinger_middle": None, "bollinger_lower": None},
        "volume": {"average_20": None, "ratio_20": None},
        "ranges": {"high_20": None, "low_20": None, "high_52w": None, "low_52w": None},
        "technical_bias": {"score": 0, "label": "neutral"},
    }


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    multiplier = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append((value - result[-1]) * multiplier + result[-1])
    return result


def _rsi(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    changes = [current - previous for previous, current in zip(values, values[1:])]
    gains = [max(change, 0) for change in changes[-period:]]
    losses = [abs(min(change, 0)) for change in changes[-period:]]
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0
    rs = average_gain / average_loss
    return 100 - 100 / (1 + rs)


def _macd(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(values) < 26:
        return None, None, None
    ema12 = _ema_series(values, 12)
    ema26 = _ema_series(values, 26)
    macd_series = [fast - slow for fast, slow in zip(ema12, ema26)]
    signal_series = _ema_series(macd_series, 9)
    return macd_series[-1], signal_series[-1], macd_series[-1] - signal_series[-1]


def _atr(history: list[dict], period: int) -> float | None:
    if len(history) <= period:
        return None
    true_ranges = []
    for previous, current in zip(history, history[1:]):
        true_ranges.append(max(
            float(current["high"]) - float(current["low"]),
            abs(float(current["high"]) - float(previous["close"])),
            abs(float(current["low"]) - float(previous["close"])),
        ))
    return sum(true_ranges[-period:]) / period


def _annualized_volatility(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    returns = [math.log(current / previous) for previous, current in zip(values, values[1:]) if previous > 0 and current > 0]
    if len(returns) < 2:
        return None
    return statistics.stdev(returns) * math.sqrt(252) * 100


def _bollinger(values: list[float], period: int) -> tuple[float | None, float | None, float | None]:
    if len(values) < period:
        return None, None, None
    window = values[-period:]
    middle = sum(window) / period
    deviation = statistics.pstdev(window)
    return middle + 2 * deviation, middle, middle - 2 * deviation
