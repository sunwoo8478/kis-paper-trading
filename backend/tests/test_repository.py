import sqlite3

import pytest

from app import repository
from app.market_data.base import OhlcvBar, Stock


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    repository.init_db(connection, initial_capital=1_000_000.0)
    yield connection
    connection.close()


def test_init_db_enables_wal_mode_and_busy_timeout(tmp_path):
    db_path = str(tmp_path / "wal-test.db")
    connection = sqlite3.connect(db_path)
    repository.init_db(connection)

    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    connection.close()


def test_init_db_sets_initial_cash_balance(conn):
    assert repository.get_cash_balance(conn) == 1_000_000.0


def test_apply_buy_creates_position_and_deducts_cash(conn):
    repository.apply_buy(conn, "005930", 10, 70000.0)
    position = repository.get_position(conn, "005930")
    assert position.quantity == 10
    assert position.avg_price == 70000.0
    assert repository.get_cash_balance(conn) == 300_000.0


def test_apply_buy_twice_averages_position(conn):
    repository.apply_buy(conn, "005930", 10, 70000.0)
    repository.apply_buy(conn, "005930", 10, 72000.0)
    position = repository.get_position(conn, "005930")
    assert position.quantity == 20
    assert position.avg_price == pytest.approx(71000.0)


def test_apply_sell_returns_realized_pnl_and_credits_cash(conn):
    repository.apply_buy(conn, "005930", 10, 70000.0)
    realized_pnl = repository.apply_sell(conn, "005930", 10, 75000.0)
    assert realized_pnl == pytest.approx(50_000.0)
    assert repository.get_position(conn, "005930") is None
    assert repository.get_cash_balance(conn) == pytest.approx(1_050_000.0)


def test_apply_sell_without_position_raises(conn):
    with pytest.raises(ValueError):
        repository.apply_sell(conn, "005930", 1, 70000.0)


def test_record_order_and_get_orders(conn):
    order_id = repository.record_order(conn, "005930", "buy", 10, 70000.0)
    orders = repository.get_orders(conn)
    assert orders[0]["id"] == order_id
    assert orders[0]["code"] == "005930"
    assert orders[0]["side"] == "buy"
    assert orders[0]["status"] == "filled"


def test_insert_snapshot_and_get_snapshots(conn):
    repository.insert_snapshot(conn, total_value=1_000_000.0, cash=1_000_000.0, evaluated_value=0.0, pnl=0.0)
    snapshots = repository.get_snapshots(conn)
    assert len(snapshots) == 1
    assert snapshots[0]["total_value"] == 1_000_000.0


def test_start_paper_experiment_archives_state_and_resets_account(conn):
    repository.apply_buy(conn, "005930", 10, 70_000.0)
    repository.record_order(conn, "005930", "buy", 10, 70_000.0)

    experiment = repository.start_paper_experiment(
        conn, "AI 기준 실험", 2_000_000.0, "autonomous-v2"
    )

    assert experiment["status"] == "active"
    assert repository.get_cash_balance(conn) == 2_000_000.0
    assert repository.get_all_positions(conn) == []
    archived = conn.execute(
        "SELECT previous_state FROM paper_experiments WHERE id = ?", (experiment["id"],)
    ).fetchone()[0]
    assert '"005930"' in archived
    performance = repository.get_experiment_performance(conn, 2_020_000.0)
    assert performance["return_pct"] == pytest.approx(1.0)
    assert performance["order_count"] == 0


def test_autonomous_lease_prevents_duplicate_workers(conn):
    assert repository.acquire_autonomous_lease(conn, "worker-a", 60) is True
    assert repository.acquire_autonomous_lease(conn, "worker-b", 60) is False
    repository.release_autonomous_lease(conn, "worker-a")
    assert repository.acquire_autonomous_lease(conn, "worker-b", 60) is True


from dataclasses import dataclass


@dataclass
class _FakeStock:
    code: str
    name: str
    market: str


@dataclass
class _FakeBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def test_upsert_and_search_stocks(conn):
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="삼성전자", market="KOSPI")])
    results = repository.search_stocks(conn, "삼성")
    assert results == [
        {
            "code": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "last_price": None,
            "prev_close": None,
            "change_pct": None,
        }
    ]


def test_search_stocks_computes_change_pct_from_price_history(conn):
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="삼성전자", market="KOSPI")])
    repository.upsert_price_history(
        conn,
        "005930",
        [
            _FakeBar(date="2026-08-26", open=69000, high=70500, low=68500, close=70000, volume=900_000),
            _FakeBar(date="2026-08-27", open=70000, high=71000, low=69500, close=70700, volume=1_000_000),
        ],
    )
    results = repository.search_stocks(conn, "005930")
    assert results[0]["last_price"] == 70700
    assert results[0]["prev_close"] == 70000
    assert results[0]["change_pct"] == pytest.approx(1.0)


def test_upsert_stocks_updates_existing_row(conn):
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="old", market="KOSPI")])
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="삼성전자", market="KOSPI")])
    results = repository.search_stocks(conn, "005930")
    assert results[0]["code"] == "005930"
    assert results[0]["name"] == "삼성전자"
    assert results[0]["market"] == "KOSPI"


def test_upsert_and_get_price_history(conn):
    bar = _FakeBar(date="2026-08-27", open=70000, high=71000, low=69500, close=70500, volume=1_000_000)
    repository.upsert_price_history(conn, "005930", [bar])
    history = repository.get_price_history(conn, "005930")
    assert history == [
        {"date": "2026-08-27", "open": 70000, "high": 71000, "low": 69500, "close": 70500, "volume": 1_000_000}
    ]


def test_get_average_volume_averages_recent_bars(conn):
    repository.upsert_stocks(conn, [Stock("005930", "삼성전자", "KOSPI")])
    bars = [
        OhlcvBar(date=f"2026-06-{i + 1:02d}", open=100, high=110, low=90, close=100, volume=1000 + i * 10)
        for i in range(30)
    ]
    repository.upsert_price_history(conn, "005930", bars)

    average = repository.get_average_volume(conn, "005930", days=20)

    expected_bars = bars[-20:]
    assert average == sum(bar.volume for bar in expected_bars) / 20


def test_get_average_volume_returns_none_when_no_history(conn):
    assert repository.get_average_volume(conn, "999999") is None


def test_watchlist_add_remove_and_list(conn):
    repository.upsert_stocks(
        conn,
        [
            _FakeStock(code="005930", name="삼성전자", market="KOSPI"),
            _FakeStock(code="000660", name="SK하이닉스", market="KOSPI"),
        ],
    )
    repository.add_watchlist(conn, "005930")
    repository.add_watchlist(conn, "000660")
    assert [w["code"] for w in repository.get_watchlist(conn)] == ["000660", "005930"]
    repository.remove_watchlist(conn, "000660")
    assert [w["code"] for w in repository.get_watchlist(conn)] == ["005930"]


def test_get_candidates_combines_top_change_top_volume_watchlist_and_positions(conn):
    repository.upsert_stocks(
        conn,
        [
            _FakeStock(code="000001", name="big-mover", market="KOSPI"),
            _FakeStock(code="000002", name="high-volume", market="KOSPI"),
            _FakeStock(code="000003", name="quiet", market="KOSPI"),
            _FakeStock(code="000004", name="watched-only", market="KOSPI"),
            _FakeStock(code="000005", name="held-only", market="KOSPI"),
        ],
    )
    bars = {
        "000001": [(69000, 900_000), (90000, 900_000)],  # +30% change, low volume
        "000002": [(70000, 100), (70100, 5_000_000)],  # tiny change, huge volume
        "000003": [(70000, 100), (70050, 100)],  # neither
        "000004": [(70000, 100), (70050, 100)],  # only via watchlist
        "000005": [(70000, 100), (70050, 100)],  # only via position
    }
    for code, prices in bars.items():
        repository.upsert_price_history(
            conn,
            code,
            [
                _FakeBar(date="2026-08-26", open=prices[0][0], high=prices[0][0], low=prices[0][0], close=prices[0][0], volume=prices[0][1]),
                _FakeBar(date="2026-08-27", open=prices[1][0], high=prices[1][0], low=prices[1][0], close=prices[1][0], volume=prices[1][1]),
            ],
        )
    repository.add_watchlist(conn, "000004")
    repository.apply_buy(conn, "000005", 1, 70050.0)

    candidates = repository.get_candidates(conn, top_change=1, top_volume=1)

    codes = {c["code"] for c in candidates}
    assert codes == {"000001", "000002", "000004", "000005"}
    assert "000003" not in codes


def test_insert_and_get_agent_runs(conn):
    run_id = repository.insert_agent_run(
        conn,
        candidates='["005930"]',
        decisions='[{"code": "005930", "action": "buy", "quantity": 1}]',
        reasoning="strong momentum",
        order_ids="[1]",
    )
    runs = repository.get_agent_runs(conn)
    assert runs[0]["id"] == run_id
    assert runs[0]["candidates"] == '["005930"]'
    assert runs[0]["reasoning"] == "strong momentum"
