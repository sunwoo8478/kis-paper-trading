from fastapi import APIRouter, Request

from .. import repository
from ..analytics import calculate_stock_analytics
from ..portfolio import compute_portfolio_value

router = APIRouter()


@router.get("/stocks/{code}/analytics")
def stock_analytics(code: str, request: Request):
    history = repository.get_price_history(request.app.state.conn, code)
    return calculate_stock_analytics(history)


@router.get("/portfolio/risk")
def portfolio_risk(request: Request):
    return build_portfolio_risk(request.app.state.conn, request.app.state.provider)


def build_portfolio_risk(conn, provider) -> dict:
    cash = repository.get_cash_balance(conn)
    initial_capital = repository.get_initial_capital(conn)
    positions = repository.get_all_positions(conn)
    prices = {}
    for position in positions:
        try:
            prices[position.code] = provider.get_latest_price(position.code)
        except Exception:
            prices[position.code] = position.avg_price

    values = compute_portfolio_value(cash, positions, prices)
    total_value = values["total_value"]
    evaluated_value = values["evaluated_value"]
    enriched = []
    for position in positions:
        current_price = prices[position.code]
        market_value = current_price * position.quantity
        cost_basis = position.avg_price * position.quantity
        enriched.append({
            "code": position.code,
            "quantity": position.quantity,
            "avg_price": position.avg_price,
            "current_price": current_price,
            "market_value": market_value,
            "cost_basis": cost_basis,
            "unrealized_pnl": market_value - cost_basis,
            "return_pct": ((current_price - position.avg_price) / position.avg_price * 100) if position.avg_price else 0,
            "weight_pct": (market_value / evaluated_value * 100) if evaluated_value else 0,
        })

    weights = [item["weight_pct"] / 100 for item in enriched]
    max_weight = max((item["weight_pct"] for item in enriched), default=0)
    snapshots = repository.get_snapshots(conn)
    values_for_drawdown = [float(item["total_value"]) for item in snapshots] + [total_value]
    peak = 0.0
    max_drawdown = 0.0
    for value in values_for_drawdown:
        peak = max(peak, value)
        if peak:
            max_drawdown = min(max_drawdown, (value - peak) / peak * 100)

    flags = []
    if max_weight >= 40:
        flags.append({"level": "warning", "code": "concentration", "message": "단일 종목 비중이 40% 이상입니다."})
    if total_value and cash / total_value * 100 < 5:
        flags.append({"level": "warning", "code": "low_cash", "message": "현금 비중이 5% 미만입니다."})
    if max_drawdown <= -10:
        flags.append({"level": "danger", "code": "drawdown", "message": "최대 낙폭이 -10% 이하입니다."})

    return {
        **values,
        "initial_capital": initial_capital,
        "total_return_pct": ((total_value - initial_capital) / initial_capital * 100) if initial_capital else 0,
        "cash_ratio_pct": (cash / total_value * 100) if total_value else 0,
        "invested_ratio_pct": (evaluated_value / total_value * 100) if total_value else 0,
        "max_position_weight_pct": max_weight,
        "concentration_hhi": sum(weight * weight for weight in weights),
        "max_drawdown_pct": max_drawdown,
        "positions": sorted(enriched, key=lambda item: item["market_value"], reverse=True),
        "risk_flags": flags,
    }
