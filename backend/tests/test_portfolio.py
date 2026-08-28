import pytest

from app.portfolio import Position, apply_buy_fill, apply_sell_fill, compute_portfolio_value


def test_apply_buy_fill_opens_new_position():
    result = apply_buy_fill(None, "005930", 10, 70000.0)
    assert result == Position(code="005930", quantity=10, avg_price=70000.0)


def test_apply_buy_fill_averages_into_existing_position():
    existing = Position(code="005930", quantity=10, avg_price=70000.0)
    result = apply_buy_fill(existing, "005930", 10, 72000.0)
    assert result.quantity == 20
    assert result.avg_price == pytest.approx(71000.0)


def test_apply_sell_fill_partial_keeps_avg_price():
    existing = Position(code="005930", quantity=10, avg_price=70000.0)
    new_position, realized_pnl = apply_sell_fill(existing, 4, 75000.0)
    assert new_position == Position(code="005930", quantity=6, avg_price=70000.0)
    assert realized_pnl == pytest.approx(20000.0)


def test_apply_sell_fill_full_closes_position():
    existing = Position(code="005930", quantity=10, avg_price=70000.0)
    new_position, realized_pnl = apply_sell_fill(existing, 10, 65000.0)
    assert new_position is None
    assert realized_pnl == pytest.approx(-50000.0)


def test_apply_sell_fill_rejects_overselling():
    existing = Position(code="005930", quantity=5, avg_price=70000.0)
    with pytest.raises(ValueError):
        apply_sell_fill(existing, 6, 70000.0)


def test_compute_portfolio_value():
    positions = [Position(code="005930", quantity=10, avg_price=70000.0)]
    value = compute_portfolio_value(
        cash=1_000_000.0, positions=positions, current_prices={"005930": 75000.0}
    )
    assert value["cash"] == 1_000_000.0
    assert value["evaluated_value"] == 750_000.0
    assert value["total_value"] == 1_750_000.0
    assert value["unrealized_pnl"] == pytest.approx(50_000.0)
