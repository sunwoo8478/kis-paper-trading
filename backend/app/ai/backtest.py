import math
import os

from .. import repository
from ..analytics import calculate_stock_analytics
from .competition import (
    competition_market_regime,
    competition_target_exposure_pct,
    position_target_pct,
    rank_competition_candidates,
)


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
    traded_value = 0.0
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
                traded_value += fill * position["quantity"]
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
            traded_value += fill * quantity
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

    gains = sum(value for value in realized_returns if value > 0)
    losses = sum(-value for value in realized_returns if value < 0)
    profit_factor = (gains / losses) if losses > 0 else (None if gains == 0 else float("inf"))
    turnover_pct = (traded_value / initial_capital * 100) if initial_capital else 0.0

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
        "profit_factor": profit_factor,
        "turnover_pct": turnover_pct,
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
        "profit_factor": None,
        "turnover_pct": 0.0,
        "open_positions": 0,
        "equity_curve": [],
        "costs_bps": {},
    }


def _verdict(result: dict) -> str:
    alpha_pct = result.get("alpha_pct", 0)
    if result["max_drawdown_pct"] <= -20 or alpha_pct <= -10:
        return "fail"
    if result["max_drawdown_pct"] <= -12 or alpha_pct < 0:
        return "warn"
    return "pass"


def run_multi_period_backtest(
    conn, periods: tuple[int, ...] = (60, 120, 252), universe_size: int = 50
) -> dict:
    period_results = []
    for period_days in periods:
        result = run_walk_forward_backtest(conn, days=period_days, universe_size=universe_size)
        period_results.append({**result, "period_days": period_days, "verdict": _verdict(result)})

    verdict_rank = {"pass": 0, "warn": 1, "fail": 2}
    overall_verdict = max(
        (period["verdict"] for period in period_results),
        key=lambda verdict: verdict_rank[verdict],
        default="pass",
    )
    return {"periods": period_results, "overall_verdict": overall_verdict}


def run_competition_backtest(
    conn,
    days: int = 60,
    universe_size: int = 200,
) -> dict:
    """Daily walk-forward approximation of the KIS three-month competition mode."""
    days = max(30, min(days, 252))
    universe_size = max(30, min(universe_size, 500))
    rows = conn.execute(
        """
        SELECT code, AVG(close * volume) AS average_trading_value
        FROM price_history
        GROUP BY code
        HAVING COUNT(*) >= 30
        ORDER BY average_trading_value DESC
        LIMIT ?
        """,
        (universe_size,),
    ).fetchall()
    codes = [row[0] for row in rows]
    histories = {
        code: repository.get_price_history(conn, code)[-(days + 70):]
        for code in codes
    }
    names = {
        row[0]: row[1]
        for row in conn.execute(
            f"SELECT code, name FROM stocks WHERE code IN ({','.join('?' for _ in codes)})",
            codes,
        ).fetchall()
    } if codes else {}
    all_dates = sorted({bar["date"] for history in histories.values() for bar in history})[-days:]
    if len(all_dates) < 2:
        return _empty_result(days, universe_size)

    initial_capital = repository.get_initial_capital(conn)
    cash = initial_capital
    positions: dict[str, dict] = {}
    equity_curve = []
    closed_returns = []
    trade_count = 0
    traded_value = 0.0
    peak_equity = initial_capital
    hard_stop_pct = float(os.getenv("KIS_COMPETITION_HARD_STOP_PCT", "6"))
    max_position_pct = float(os.getenv("KIS_COMPETITION_MAX_POSITION_PCT", "12"))
    base_position_pct = float(os.getenv("KIS_COMPETITION_BASE_POSITION_PCT", "12"))
    max_positions = max(1, int(os.getenv("KIS_COMPETITION_MAX_POSITIONS", "10")))
    min_trading_value = float(os.getenv("KIS_COMPETITION_MIN_AVG_TRADING_VALUE", "1000000000"))

    for current_date in all_dates:
        previous_histories = {
            code: [bar for bar in history if bar["date"] < current_date]
            for code, history in histories.items()
        }
        today_bars = {
            code: next((bar for bar in history if bar["date"] == current_date), None)
            for code, history in histories.items()
        }
        ranking = rank_competition_candidates(
            [
                ({"code": code, "name": names.get(code, code)}, history)
                for code, history in previous_histories.items()
            ],
            pool_size=30,
            min_avg_trading_value=min_trading_value,
            min_price=float(os.getenv("KIS_COMPETITION_MIN_PRICE", "1000")),
            max_return_20_pct=float(os.getenv("KIS_COMPETITION_MAX_20D_RETURN_PCT", "120")),
            max_volatility_pct=float(os.getenv("KIS_COMPETITION_MAX_VOLATILITY_PCT", "120")),
        )
        by_code = {item["code"]: item for item in ranking}
        breadth = _historical_breadth(previous_histories)

        marked_before = cash + sum(
            position["quantity"] * float(
                (today_bars.get(code) or {}).get("open") or position["avg_price"]
            )
            for code, position in positions.items()
        )
        drawdown_pct = (marked_before / peak_equity - 1) * 100 if peak_equity else 0
        max_drawdown_stop_pct = float(os.getenv("KIS_COMPETITION_MAX_DRAWDOWN_STOP_PCT", "8"))
        regime = competition_market_regime(breadth, drawdown_pct, max_drawdown_stop_pct)
        target_pct = competition_target_exposure_pct(
            regime,
            drawdown_pct,
            None,
            max_drawdown_stop_pct=max_drawdown_stop_pct,
        )

        for code, position in list(positions.items()):
            today = today_bars.get(code)
            if not today:
                continue
            open_price = _positive_price(today["open"])
            if open_price is None:
                continue
            previous_peak = position["peak"]
            return_pct = (open_price / position["avg_price"] - 1) * 100
            previous = previous_histories[code]
            exit_signal = return_pct <= -hard_stop_pct
            if len(previous) >= 21:
                analytics = calculate_stock_analytics(previous)
                ma20 = analytics["moving_averages"]["ma20"]
                atr14 = analytics["volatility"]["atr14"]
                closes = [float(bar["close"]) for bar in previous]
                return_5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
                exit_signal = exit_signal or bool(ma20 and open_price < ma20 and return_5 < 0)
                if atr14 and return_pct >= 3:
                    exit_signal = exit_signal or open_price <= previous_peak - atr14 * 2.5
            if exit_signal:
                fill = _fill_price("sell", open_price)
                proceeds = fill * position["quantity"]
                cash += proceeds
                traded_value += proceeds
                closed_returns.append((fill / position["avg_price"] - 1) * 100)
                trade_count += 1
                del positions[code]
            else:
                position["peak"] = max(previous_peak, float(today["high"]), open_price)

        evaluated = sum(
            position["quantity"] * float(
                (today_bars.get(code) or {}).get("open") or position["avg_price"]
            )
            for code, position in positions.items()
        )
        target_value = (cash + evaluated) * target_pct / 100
        excess = max(0.0, evaluated - target_value)
        for code in sorted(positions, key=lambda value: by_code.get(value, {}).get("score", -1)):
            if excess <= 0:
                break
            today = today_bars.get(code)
            price = _positive_price(today["open"]) if today else None
            if price is None:
                continue
            position = positions[code]
            quantity = min(position["quantity"], max(1, math.ceil(excess / price)))
            fill = _fill_price("sell", price)
            proceeds = fill * quantity
            cash += proceeds
            traded_value += proceeds
            trade_count += 1
            excess -= price * quantity
            position["quantity"] -= quantity
            if position["quantity"] <= 0:
                closed_returns.append((fill / position["avg_price"] - 1) * 100)
                del positions[code]

        portfolio_value = cash + sum(
            position["quantity"] * float(
                (today_bars.get(code) or {}).get("open") or position["avg_price"]
            )
            for code, position in positions.items()
        )
        buy_budget = max(0.0, min(cash, portfolio_value * target_pct / 100 - (portfolio_value - cash)))
        for signal in ranking:
            if buy_budget <= 0:
                break
            code = signal["code"]
            if code in positions:
                continue
            if len(positions) >= max_positions:
                break
            today = today_bars.get(code)
            open_price = _positive_price(today["open"]) if today else None
            if open_price is None:
                continue
            target_position_pct = min(
                max_position_pct,
                position_target_pct(signal.get("volatility_pct"), base_position_pct),
            )
            allocation = min(buy_budget, portfolio_value * target_position_pct / 100)
            fill = _fill_price("buy", open_price)
            quantity = int(allocation // fill)
            if quantity <= 0:
                continue
            cost = fill * quantity
            cash -= cost
            buy_budget -= cost
            traded_value += cost
            trade_count += 1
            positions[code] = {
                "quantity": quantity,
                "avg_price": fill,
                "peak": float(today["high"]),
            }

        evaluated_close = sum(
            position["quantity"] * float(
                (today_bars.get(code) or {}).get("close") or position["avg_price"]
            )
            for code, position in positions.items()
        )
        total_value = cash + evaluated_close
        peak_equity = max(peak_equity, total_value)
        equity_curve.append({"date": current_date, "value": total_value})

    final_value = equity_curve[-1]["value"]
    max_drawdown = 0.0
    peak = 0.0
    for point in equity_curve:
        peak = max(peak, point["value"])
        if peak:
            max_drawdown = min(max_drawdown, (point["value"] / peak - 1) * 100)
    gains = sum(value for value in closed_returns if value > 0)
    losses = sum(-value for value in closed_returns if value < 0)
    return {
        "mode": "competition_3m_walk_forward",
        "start_date": all_dates[0],
        "end_date": all_dates[-1],
        "trading_days": len(all_dates),
        "universe_size": len(codes),
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return_pct": (final_value / initial_capital - 1) * 100,
        "max_drawdown_pct": max_drawdown,
        "trade_count": trade_count,
        "closed_trade_count": len(closed_returns),
        "win_rate_pct": (
            sum(value > 0 for value in closed_returns) / len(closed_returns) * 100
            if closed_returns else 0.0
        ),
        "profit_factor": gains / losses if losses else None,
        "turnover_pct": traded_value / initial_capital * 100 if initial_capital else 0.0,
        "open_positions": len(positions),
        "equity_curve": equity_curve,
        "costs_bps": {
            "slippage": float(os.getenv("SIMULATED_SLIPPAGE_BPS", "0")),
            "commission": float(os.getenv("SIMULATED_COMMISSION_BPS", "0")),
            "sell_tax": float(os.getenv("SIMULATED_SELL_TAX_BPS", "0")),
        },
    }


def _historical_breadth(histories: dict[str, list[dict]]) -> dict:
    eligible = [history for history in histories.values() if len(history) >= 20]
    if not eligible:
        return {"advancing_ratio": 0.0, "above_ma20_ratio": 0.0}
    advancing = sum(float(history[-1]["close"]) > float(history[-2]["close"]) for history in eligible)
    above_ma20 = sum(
        float(history[-1]["close"]) > sum(float(bar["close"]) for bar in history[-20:]) / 20
        for history in eligible
    )
    return {
        "advancing_ratio": advancing / len(eligible),
        "above_ma20_ratio": above_ma20 / len(eligible),
    }
