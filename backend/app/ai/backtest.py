import os

from .. import repository
from ..analytics import calculate_stock_analytics


def run_walk_forward_backtest(conn, days: int = 60, universe_size: int = 50) -> dict:
    days = max(30, min(days, 252))
    universe_size = max(10, min(universe_size, 200))
    rows = conn.execute(
        """
        SELECT code, AVG(volume) AS average_volume
        FROM price_history
        GROUP BY code
        HAVING COUNT(*) >= 30
        ORDER BY average_volume DESC
        LIMIT ?
        """,
        (universe_size,),
    ).fetchall()
    codes = [row[0] for row in rows]
    histories = {code: repository.get_price_history(conn, code)[-(days + 40):] for code in codes}
    all_dates = sorted({bar["date"] for history in histories.values() for bar in history})[-days:]
    if len(all_dates) < 2:
        return _empty_result(days, universe_size)

    initial_capital = repository.get_initial_capital(conn)
    cash = initial_capital
    positions: dict[str, dict] = {}
    equity_curve = []
    realized_returns = []
    trade_count = 0
    stop_loss_pct = float(os.getenv("AI_AUTONOMOUS_STOP_LOSS_PCT", "5"))
    take_profit_pct = float(os.getenv("AI_AUTONOMOUS_TAKE_PROFIT_PCT", "12"))
    max_positions = int(os.getenv("AI_BACKTEST_MAX_POSITIONS", "8"))
    max_position_pct = float(os.getenv("AI_MAX_POSITION_PCT", "20"))

    for current_date in all_dates:
        signals = []
        bars_today = {}
        for code, history in histories.items():
            previous = [bar for bar in history if bar["date"] < current_date]
            today = next((bar for bar in history if bar["date"] == current_date), None)
            if len(previous) < 26 or today is None:
                continue
            analytics = calculate_stock_analytics(previous)
            previous_close = _positive_price(previous[-1]["close"])
            earlier_close = _positive_price(previous[-2]["close"]) if len(previous) >= 2 else None
            if previous_close is None:
                continue
            prior_change = (
                (previous_close - earlier_close) / earlier_close * 100
                if earlier_close is not None
                else 0
            )
            signals.append({
                "code": code,
                "score": analytics["technical_bias"]["score"],
                "prior_change_pct": prior_change,
            })
            bars_today[code] = today

        for code, position in list(positions.items()):
            today = bars_today.get(code)
            signal = next((item for item in signals if item["code"] == code), None)
            if today is None:
                continue
            open_price = _positive_price(today["open"])
            if open_price is None:
                continue
            return_pct = (open_price - position["avg_price"]) / position["avg_price"] * 100
            should_sell = (
                return_pct <= -stop_loss_pct
                or return_pct >= take_profit_pct
                or (signal is not None and signal["score"] <= -25)
            )
            if should_sell:
                fill = _fill_price("sell", open_price)
                cash += fill * position["quantity"]
                realized_returns.append((fill - position["avg_price"]) / position["avg_price"] * 100)
                trade_count += 1
                del positions[code]

        buy_signals = sorted(
            (
                signal for signal in signals
                if signal["score"] >= 25
                and signal["prior_change_pct"] < 15
                and signal["code"] not in positions
            ),
            key=lambda item: item["score"],
            reverse=True,
        )
        directional = [signal["score"] for signal in signals if abs(signal["score"]) >= 25]
        if directional and sum(score > 0 for score in directional) / len(directional) <= 0.35:
            buy_signals = []
        available_slots = max_positions - len(positions)
        selected_signals = buy_signals[:available_slots]
        for index, signal in enumerate(selected_signals):
            today = bars_today[signal["code"]]
            open_price = _positive_price(today["open"])
            if open_price is None:
                continue
            fill = _fill_price("buy", open_price)
            remaining_signals = len(selected_signals) - index
            allocation = min(
                cash / remaining_signals,
                initial_capital * max_position_pct / 100,
            )
            quantity = int(allocation // fill)
            if quantity <= 0:
                continue
            cash -= fill * quantity
            positions[signal["code"]] = {"quantity": quantity, "avg_price": fill}
            trade_count += 1

        evaluated = 0.0
        for code, position in positions.items():
            today = bars_today.get(code)
            mark = _positive_price(today["close"]) if today else None
            mark = mark if mark is not None else position["avg_price"]
            evaluated += mark * position["quantity"]
        equity_curve.append({"date": current_date, "value": cash + evaluated})

    final_value = equity_curve[-1]["value"]
    benchmark_returns = []
    for history in histories.values():
        period_closes = [
            _positive_price(bar["close"])
            for bar in history
            if all_dates[0] <= bar["date"] <= all_dates[-1]
        ]
        period_closes = [price for price in period_closes if price is not None]
        if len(period_closes) >= 2 and period_closes[0]:
            benchmark_returns.append((period_closes[-1] - period_closes[0]) / period_closes[0] * 100)
    benchmark_return = (
        sum(benchmark_returns) / len(benchmark_returns) if benchmark_returns else 0.0
    )
    peak = 0.0
    max_drawdown = 0.0
    for point in equity_curve:
        peak = max(peak, point["value"])
        if peak:
            max_drawdown = min(max_drawdown, (point["value"] - peak) / peak * 100)

    return {
        "mode": "walk_forward_daily",
        "start_date": all_dates[0],
        "end_date": all_dates[-1],
        "trading_days": len(all_dates),
        "universe_size": len(codes),
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return_pct": (final_value - initial_capital) / initial_capital * 100,
        "equal_weight_benchmark_pct": benchmark_return,
        "alpha_pct": (final_value - initial_capital) / initial_capital * 100 - benchmark_return,
        "max_drawdown_pct": max_drawdown,
        "trade_count": trade_count,
        "closed_trade_count": len(realized_returns),
        "win_rate_pct": (
            sum(value > 0 for value in realized_returns) / len(realized_returns) * 100
            if realized_returns else 0
        ),
        "open_positions": len(positions),
        "equity_curve": equity_curve,
        "costs_bps": {
            "slippage": float(os.getenv("SIMULATED_SLIPPAGE_BPS", "0")),
            "commission": float(os.getenv("SIMULATED_COMMISSION_BPS", "0")),
            "sell_tax": float(os.getenv("SIMULATED_SELL_TAX_BPS", "0")),
        },
    }


def _fill_price(side: str, price: float) -> float:
    slippage = float(os.getenv("SIMULATED_SLIPPAGE_BPS", "0"))
    commission = float(os.getenv("SIMULATED_COMMISSION_BPS", "0"))
    sell_tax = float(os.getenv("SIMULATED_SELL_TAX_BPS", "0")) if side == "sell" else 0
    total = slippage + commission + sell_tax
    return price * (1 + total / 10_000 if side == "buy" else 1 - total / 10_000)


def _positive_price(value) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _empty_result(days: int, universe_size: int) -> dict:
    return {
        "mode": "walk_forward_daily",
        "start_date": None,
        "end_date": None,
        "trading_days": 0,
        "universe_size": universe_size,
        "initial_capital": 0,
        "final_value": 0,
        "total_return_pct": 0,
        "max_drawdown_pct": 0,
        "trade_count": 0,
        "closed_trade_count": 0,
        "win_rate_pct": 0,
        "open_positions": 0,
        "equity_curve": [],
        "costs_bps": {},
    }
