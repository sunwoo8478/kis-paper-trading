import pytest

from app.analytics import calculate_stock_analytics


def _history(count: int = 120) -> list[dict]:
    return [
        {
            "date": f"2026-{(index // 28) + 1:02d}-{(index % 28) + 1:02d}",
            "open": 100 + index,
            "high": 103 + index,
            "low": 98 + index,
            "close": 101 + index,
            "volume": 1_000 + index * 10,
        }
        for index in range(count)
    ]


def test_calculate_stock_analytics_returns_professional_indicators():
    result = calculate_stock_analytics(_history())

    assert result["moving_averages"]["ma20"] == pytest.approx(sum(range(201, 221)) / 20)
    assert result["moving_averages"]["ma60"] is not None
    assert result["momentum"]["rsi14"] == 100.0
    assert result["momentum"]["macd"] is not None
    assert result["volatility"]["atr14"] == pytest.approx(5.0)
    assert result["ranges"]["high_52w"] == 222
    assert result["technical_bias"]["label"] == "bullish"


def test_calculate_stock_analytics_handles_empty_history():
    result = calculate_stock_analytics([])
    assert result["close"] is None
    assert result["technical_bias"] == {"score": 0, "label": "neutral"}
