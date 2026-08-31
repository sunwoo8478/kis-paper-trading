import json
import sqlite3
from datetime import datetime, timedelta, timezone

from . import portfolio

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS watchlist (
    code TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cash_balance REAL NOT NULL,
    initial_capital REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    code TEXT PRIMARY KEY,
    quantity INTEGER NOT NULL,
    avg_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    filled_at TEXT NOT NULL,
    status TEXT NOT NULL,
    order_type TEXT NOT NULL DEFAULT 'market',
    limit_price REAL,
    requested_quantity INTEGER,
    filled_quantity INTEGER NOT NULL DEFAULT 0,
    fill_reason TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    total_value REAL NOT NULL,
    cash REAL NOT NULL,
    evaluated_value REAL NOT NULL,
    pnl REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    candidates TEXT NOT NULL,
    decisions TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    order_ids TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomous_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomous_lease (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    owner TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomous_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    market_open INTEGER NOT NULL,
    decisions TEXT NOT NULL,
    order_ids TEXT NOT NULL,
    total_value REAL,
    error TEXT,
    market_regime TEXT,
    target_exposure_pct REAL,
    blocked_decisions TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS paper_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    initial_capital REAL NOT NULL,
    benchmark_symbol TEXT,
    benchmark_start_value REAL,
    previous_state TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    direction TEXT NOT NULL,
    target_price REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    triggered_at TEXT
);

CREATE TABLE IF NOT EXISTS trade_journal (
    code TEXT PRIMARY KEY,
    thesis TEXT NOT NULL DEFAULT '',
    invalidation TEXT NOT NULL DEFAULT '',
    target_price REAL,
    tags TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);
"""


def init_db(conn: sqlite3.Connection, initial_capital: float = 10_000_000.0) -> None:
    conn.executescript(SCHEMA)
    _ensure_column(conn, "orders", "order_type", "TEXT NOT NULL DEFAULT 'market'")
    _ensure_column(conn, "orders", "limit_price", "REAL")
    _ensure_column(conn, "orders", "requested_quantity", "INTEGER")
    _ensure_column(conn, "orders", "filled_quantity", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "orders", "fill_reason", "TEXT")
    conn.execute(
        """
        UPDATE orders
        SET requested_quantity = COALESCE(requested_quantity, quantity),
            filled_quantity = CASE
                WHEN filled_quantity = 0 AND status = 'filled' THEN quantity
                ELSE filled_quantity
            END
        WHERE requested_quantity IS NULL
           OR (filled_quantity = 0 AND status = 'filled')
        """
    )
    _ensure_column(conn, "paper_experiments", "benchmark_symbol", "TEXT")
    _ensure_column(conn, "paper_experiments", "benchmark_start_value", "REAL")
    _ensure_column(conn, "autonomous_cycles", "market_regime", "TEXT")
    _ensure_column(conn, "autonomous_cycles", "target_exposure_pct", "REAL")
    _ensure_column(
        conn,
        "autonomous_cycles",
        "blocked_decisions",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    conn.execute(
        "INSERT OR IGNORE INTO account (id, cash_balance, initial_capital) VALUES (1, ?, ?)",
        (initial_capital, initial_capital),
    )
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def get_cash_balance(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT cash_balance FROM account WHERE id = 1").fetchone()
    return row[0]


def get_initial_capital(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT initial_capital FROM account WHERE id = 1").fetchone()
    return row[0]


def start_paper_experiment(
    conn: sqlite3.Connection,
    name: str,
    initial_capital: float,
    strategy_version: str,
    benchmark_symbol: str | None = None,
    benchmark_start_value: float | None = None,
) -> dict:
    if initial_capital <= 0:
        raise ValueError("initial capital must be positive")
    started_at = datetime.now(timezone.utc).isoformat()
    previous_state = json.dumps(
        {
            "cash": get_cash_balance(conn),
            "initial_capital": get_initial_capital(conn),
            "positions": [
                {"code": item.code, "quantity": item.quantity, "avg_price": item.avg_price}
                for item in get_all_positions(conn)
            ],
            "latest_order_id": conn.execute("SELECT MAX(id) FROM orders").fetchone()[0],
            "latest_snapshot_id": conn.execute("SELECT MAX(id) FROM portfolio_snapshots").fetchone()[0],
        },
        ensure_ascii=False,
    )
    conn.execute(
        "UPDATE paper_experiments SET status = 'completed', ended_at = ? WHERE status = 'active'",
        (started_at,),
    )
    cursor = conn.execute(
        """
        INSERT INTO paper_experiments
        (name, strategy_version, started_at, initial_capital, benchmark_symbol,
         benchmark_start_value, previous_state, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            name, strategy_version, started_at, initial_capital, benchmark_symbol,
            benchmark_start_value, previous_state,
        ),
    )
    conn.execute("DELETE FROM positions")
    conn.execute("UPDATE orders SET status = 'cancelled' WHERE status = 'pending'")
    conn.execute(
        "UPDATE account SET cash_balance = ?, initial_capital = ? WHERE id = 1",
        (initial_capital, initial_capital),
    )
    conn.execute(
        "INSERT INTO portfolio_snapshots (ts, total_value, cash, evaluated_value, pnl) VALUES (?, ?, ?, 0, 0)",
        (started_at, initial_capital, initial_capital),
    )
    conn.commit()
    return get_active_experiment(conn)


def get_active_experiment(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        """
        SELECT id, name, strategy_version, started_at, ended_at, initial_capital,
               benchmark_symbol, benchmark_start_value, status
        FROM paper_experiments WHERE status = 'active' ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "name": row[1], "strategy_version": row[2],
        "started_at": row[3], "ended_at": row[4], "initial_capital": row[5],
        "benchmark_symbol": row[6], "benchmark_start_value": row[7], "status": row[8],
    }


def get_experiment_performance(
    conn: sqlite3.Connection,
    current_total: float,
    current_benchmark_value: float | None = None,
) -> dict | None:
    experiment = get_active_experiment(conn)
    if experiment is None:
        return None
    initial = float(experiment["initial_capital"])
    snapshots = conn.execute(
        "SELECT ts, total_value FROM portfolio_snapshots WHERE ts >= ? ORDER BY ts",
        (experiment["started_at"],),
    ).fetchall()
    values = [initial] + [float(row[1]) for row in snapshots] + [float(current_total)]
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            max_drawdown = min(max_drawdown, (value - peak) / peak * 100)
    order_count = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE filled_at >= ? AND status = 'filled'",
        (experiment["started_at"],),
    ).fetchone()[0]
    cycle_count = conn.execute(
        "SELECT COUNT(*) FROM autonomous_cycles WHERE started_at >= ?",
        (experiment["started_at"],),
    ).fetchone()[0]
    benchmark_start = experiment.get("benchmark_start_value")
    benchmark_return = (
        (current_benchmark_value - benchmark_start) / benchmark_start * 100
        if current_benchmark_value is not None and benchmark_start
        else None
    )
    strategy_return = (current_total - initial) / initial * 100 if initial else 0
    return {
        **experiment,
        "current_value": current_total,
        "return_pct": strategy_return,
        "benchmark_current_value": current_benchmark_value,
        "benchmark_return_pct": benchmark_return,
        "alpha_pct": strategy_return - benchmark_return if benchmark_return is not None else None,
        "max_drawdown_pct": max_drawdown,
        "order_count": order_count,
        "cycle_count": cycle_count,
    }


def acquire_autonomous_lease(conn: sqlite3.Connection, owner: str, ttl_seconds: int) -> bool:
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=max(30, ttl_seconds))).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT owner, expires_at FROM autonomous_lease WHERE id = 1").fetchone()
    if row is not None and row[0] != owner and datetime.fromisoformat(row[1]) > now:
        conn.rollback()
        return False
    conn.execute(
        """
        INSERT INTO autonomous_lease (id, owner, expires_at) VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET owner = excluded.owner, expires_at = excluded.expires_at
        """,
        (owner, expires_at),
    )
    conn.commit()
    return True


def release_autonomous_lease(conn: sqlite3.Connection, owner: str) -> None:
    conn.execute("DELETE FROM autonomous_lease WHERE id = 1 AND owner = ?", (owner,))
    conn.commit()


def get_position(conn: sqlite3.Connection, code: str) -> portfolio.Position | None:
    row = conn.execute(
        "SELECT code, quantity, avg_price FROM positions WHERE code = ?", (code,)
    ).fetchone()
    if row is None:
        return None
    return portfolio.Position(code=row[0], quantity=row[1], avg_price=row[2])


def get_all_positions(conn: sqlite3.Connection) -> list[portfolio.Position]:
    rows = conn.execute("SELECT code, quantity, avg_price FROM positions").fetchall()
    return [portfolio.Position(code=r[0], quantity=r[1], avg_price=r[2]) for r in rows]


def apply_buy(conn: sqlite3.Connection, code: str, quantity: int, price: float, commit: bool = True) -> None:
    existing = get_position(conn, code)
    new_position = portfolio.apply_buy_fill(existing, code, quantity, price)
    conn.execute(
        "INSERT INTO positions (code, quantity, avg_price) VALUES (?, ?, ?) "
        "ON CONFLICT(code) DO UPDATE SET quantity = excluded.quantity, avg_price = excluded.avg_price",
        (new_position.code, new_position.quantity, new_position.avg_price),
    )
    conn.execute(
        "UPDATE account SET cash_balance = cash_balance - ? WHERE id = 1",
        (price * quantity,),
    )
    if commit:
        conn.commit()


def apply_sell(conn: sqlite3.Connection, code: str, quantity: int, price: float, commit: bool = True) -> float:
    existing = get_position(conn, code)
    if existing is None:
        raise ValueError(f"no position for {code}")
    new_position, realized_pnl = portfolio.apply_sell_fill(existing, quantity, price)
    if new_position is None:
        conn.execute("DELETE FROM positions WHERE code = ?", (code,))
    else:
        conn.execute(
            "UPDATE positions SET quantity = ?, avg_price = ? WHERE code = ?",
            (new_position.quantity, new_position.avg_price, code),
        )
    conn.execute(
        "UPDATE account SET cash_balance = cash_balance + ? WHERE id = 1",
        (price * quantity,),
    )
    if commit:
        conn.commit()
    return realized_pnl


def record_order(
    conn: sqlite3.Connection,
    code: str,
    side: str,
    quantity: int,
    price: float,
    status: str = "filled",
    order_type: str = "market",
    limit_price: float | None = None,
    commit: bool = True,
    requested_quantity: int | None = None,
    filled_quantity: int | None = None,
    fill_reason: str | None = None,
) -> int:
    filled_at = datetime.now(timezone.utc).isoformat()
    requested_quantity = quantity if requested_quantity is None else requested_quantity
    if filled_quantity is None:
        filled_quantity = quantity if status == "filled" else 0
    cursor = conn.execute(
        """
        INSERT INTO orders
            (code, side, quantity, price, filled_at, status, order_type, limit_price,
             requested_quantity, filled_quantity, fill_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code, side, quantity, price, filled_at, status, order_type, limit_price,
            requested_quantity, filled_quantity, fill_reason,
        ),
    )
    if commit:
        conn.commit()
    return cursor.lastrowid


def get_orders(conn: sqlite3.Connection, since: str | None = None) -> list[dict]:
    if since is None:
        rows = conn.execute(
            """
            SELECT id, code, side, quantity, price, filled_at, status, order_type,
                   limit_price, requested_quantity, filled_quantity, fill_reason
            FROM orders ORDER BY id DESC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, code, side, quantity, price, filled_at, status, order_type,
                   limit_price, requested_quantity, filled_quantity, fill_reason
            FROM orders WHERE filled_at >= ? ORDER BY id DESC
            """,
            (since,),
        ).fetchall()
    return [
        {
            "id": r[0], "code": r[1], "side": r[2], "quantity": r[3],
            "price": r[4], "filled_at": r[5], "status": r[6],
            "order_type": r[7], "limit_price": r[8],
            "requested_quantity": r[9] if r[9] is not None else r[3],
            "filled_quantity": r[10], "fill_reason": r[11],
        }
        for r in rows
    ]


def get_pending_orders(conn: sqlite3.Connection) -> list[dict]:
    return [order for order in get_orders(conn) if order["status"] == "pending"]


def fill_pending_order(
    conn: sqlite3.Connection,
    order_id: int,
    price: float,
    filled_quantity: int,
    status: str = "filled",
    fill_reason: str | None = None,
) -> None:
    filled_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        UPDATE orders
        SET price = ?, filled_at = ?, status = ?, filled_quantity = ?, fill_reason = ?
        WHERE id = ? AND status = 'pending'
        """,
        (price, filled_at, status, filled_quantity, fill_reason, order_id),
    )
    if cursor.rowcount != 1:
        conn.rollback()
        raise ValueError("pending order not found")
    conn.commit()


def cancel_pending_order(conn: sqlite3.Connection, order_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE orders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
        (order_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_pending_commitments(conn: sqlite3.Connection) -> tuple[float, dict[str, int]]:
    rows = conn.execute(
        "SELECT code, side, quantity, limit_price FROM orders WHERE status = 'pending'"
    ).fetchall()
    buy_value = sum((row[3] or 0) * row[2] for row in rows if row[1] == "buy")
    sell_quantities: dict[str, int] = {}
    for code, side, quantity, _ in rows:
        if side == "sell":
            sell_quantities[code] = sell_quantities.get(code, 0) + quantity
    return buy_value, sell_quantities


def get_average_volume(conn: sqlite3.Connection, code: str, days: int = 20) -> float | None:
    row = conn.execute(
        """
        SELECT AVG(volume)
        FROM (
            SELECT volume FROM price_history
            WHERE code = ? AND volume > 0
            ORDER BY date DESC LIMIT ?
        )
        """,
        (code, max(1, days)),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def create_price_alert(conn: sqlite3.Connection, code: str, direction: str, target_price: float) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO price_alerts (code, direction, target_price, active, created_at) VALUES (?, ?, ?, 1, ?)",
        (code, direction, target_price, created_at),
    )
    conn.commit()
    return cursor.lastrowid


def get_price_alerts(conn: sqlite3.Connection, code: str | None = None) -> list[dict]:
    if code is None:
        rows = conn.execute(
            "SELECT id, code, direction, target_price, active, created_at, triggered_at FROM price_alerts ORDER BY id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, code, direction, target_price, active, created_at, triggered_at FROM price_alerts WHERE code = ? ORDER BY id DESC",
            (code,),
        ).fetchall()
    return [
        {
            "id": row[0], "code": row[1], "direction": row[2], "target_price": row[3],
            "active": bool(row[4]), "created_at": row[5], "triggered_at": row[6],
        }
        for row in rows
    ]


def trigger_price_alert(conn: sqlite3.Connection, alert_id: int) -> None:
    triggered_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE price_alerts SET active = 0, triggered_at = ? WHERE id = ?",
        (triggered_at, alert_id),
    )
    conn.commit()


def delete_price_alert(conn: sqlite3.Connection, alert_id: int) -> bool:
    cursor = conn.execute("DELETE FROM price_alerts WHERE id = ?", (alert_id,))
    conn.commit()
    return cursor.rowcount > 0


def upsert_journal_entry(
    conn: sqlite3.Connection,
    code: str,
    thesis: str,
    invalidation: str,
    target_price: float | None,
    tags: str,
) -> dict:
    updated_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO trade_journal (code, thesis, invalidation, target_price, tags, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            thesis = excluded.thesis,
            invalidation = excluded.invalidation,
            target_price = excluded.target_price,
            tags = excluded.tags,
            updated_at = excluded.updated_at
        """,
        (code, thesis, invalidation, target_price, tags, updated_at),
    )
    conn.commit()
    return get_journal_entry(conn, code)


def get_journal_entry(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute(
        "SELECT code, thesis, invalidation, target_price, tags, updated_at FROM trade_journal WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        return None
    return {
        "code": row[0], "thesis": row[1], "invalidation": row[2],
        "target_price": row[3], "tags": row[4], "updated_at": row[5],
    }


def get_journal_entries(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT code, thesis, invalidation, target_price, tags, updated_at FROM trade_journal ORDER BY updated_at DESC"
    ).fetchall()
    return [
        {"code": row[0], "thesis": row[1], "invalidation": row[2], "target_price": row[3], "tags": row[4], "updated_at": row[5]}
        for row in rows
    ]


def insert_snapshot(
    conn: sqlite3.Connection, total_value: float, cash: float, evaluated_value: float, pnl: float
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO portfolio_snapshots (ts, total_value, cash, evaluated_value, pnl) VALUES (?, ?, ?, ?, ?)",
        (ts, total_value, cash, evaluated_value, pnl),
    )
    conn.commit()


def get_snapshots(conn: sqlite3.Connection, since: str | None = None) -> list[dict]:
    if since is None:
        rows = conn.execute(
            "SELECT ts, total_value, cash, evaluated_value, pnl FROM portfolio_snapshots ORDER BY ts"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ts, total_value, cash, evaluated_value, pnl FROM portfolio_snapshots WHERE ts >= ? ORDER BY ts",
            (since,),
        ).fetchall()
    return [
        {"ts": r[0], "total_value": r[1], "cash": r[2], "evaluated_value": r[3], "pnl": r[4]}
        for r in rows
    ]


def upsert_stocks(conn: sqlite3.Connection, stocks: list) -> None:
    conn.executemany(
        "INSERT INTO stocks (code, name, market) VALUES (?, ?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name = excluded.name, market = excluded.market",
        [(s.code, s.name, s.market) for s in stocks],
    )
    conn.commit()


_QUOTE_JOIN = """
    LEFT JOIN (
        SELECT code, close, ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
        FROM price_history
    ) latest ON latest.code = s.code AND latest.rn = 1
    LEFT JOIN (
        SELECT code, close, ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
        FROM price_history
    ) prev ON prev.code = s.code AND prev.rn = 2
"""


def _quote_row_to_dict(row: tuple) -> dict:
    code, name, market, last_price, prev_close = row
    change_pct = None
    if last_price is not None and prev_close:
        change_pct = (last_price - prev_close) / prev_close * 100
    return {
        "code": code,
        "name": name,
        "market": market,
        "last_price": last_price,
        "prev_close": prev_close,
        "change_pct": change_pct,
    }


def search_stocks(conn: sqlite3.Connection, query: str) -> list[dict]:
    like = f"%{query}%"
    rows = conn.execute(
        f"""
        SELECT s.code, s.name, s.market, latest.close, prev.close
        FROM stocks s
        {_QUOTE_JOIN}
        WHERE s.code LIKE ? OR s.name LIKE ?
        ORDER BY s.code
        """,
        (like, like),
    ).fetchall()
    return [_quote_row_to_dict(row) for row in rows]


def find_stocks_in_text(conn: sqlite3.Connection, text: str, limit: int = 5) -> list[dict]:
    normalized_text = "".join(text.lower().split())
    rows = conn.execute("SELECT code, name, market FROM stocks").fetchall()
    matches = [
        {"code": row[0], "name": row[1], "market": row[2]}
        for row in rows
        if row[0].lower() in normalized_text
        or (
            len("".join(row[1].split())) >= 2
            and "".join(row[1].lower().split()) in normalized_text
        )
    ]
    matches.sort(key=lambda stock: (-len("".join(stock["name"].split())), stock["code"]))
    return matches[:limit]


def get_stock(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute("SELECT code, name, market FROM stocks WHERE code = ?", (code,)).fetchone()
    if row is None:
        return None
    return {"code": row[0], "name": row[1], "market": row[2]}


def upsert_price_history(conn: sqlite3.Connection, code: str, bars: list) -> None:
    conn.executemany(
        "INSERT INTO price_history (code, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(code, date) DO UPDATE SET open=excluded.open, high=excluded.high, "
        "low=excluded.low, close=excluded.close, volume=excluded.volume",
        [(code, b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars],
    )
    conn.commit()


def get_price_history(conn: sqlite3.Connection, code: str) -> list[dict]:
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM price_history WHERE code = ? ORDER BY date",
        (code,),
    ).fetchall()
    return [
        {"date": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
        for r in rows
    ]


def add_watchlist(conn: sqlite3.Connection, code: str) -> None:
    conn.execute("INSERT OR IGNORE INTO watchlist (code) VALUES (?)", (code,))
    conn.commit()


def remove_watchlist(conn: sqlite3.Connection, code: str) -> None:
    conn.execute("DELETE FROM watchlist WHERE code = ?", (code,))
    conn.commit()


def get_watchlist(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT w.code, COALESCE(s.name, w.code), COALESCE(s.market, ''), latest.close, prev.close
        FROM watchlist w
        LEFT JOIN stocks s ON s.code = w.code
        LEFT JOIN (
            SELECT code, close, ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
            FROM price_history
        ) latest ON latest.code = w.code AND latest.rn = 1
        LEFT JOIN (
            SELECT code, close, ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
            FROM price_history
        ) prev ON prev.code = w.code AND prev.rn = 2
        ORDER BY w.code
        """
    ).fetchall()
    return [_quote_row_to_dict(row) for row in rows]


def get_candidates(conn: sqlite3.Connection, top_change: int = 30, top_volume: int = 20) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT s.code, s.name, s.market, latest.close, prev.close, latest_vol.volume
        FROM stocks s
        {_QUOTE_JOIN}
        LEFT JOIN (
            SELECT code, volume, ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
            FROM price_history
        ) latest_vol ON latest_vol.code = s.code AND latest_vol.rn = 1
        WHERE latest.close IS NOT NULL
        """
    ).fetchall()

    quotes = []
    for code, name, market, last_price, prev_close, volume in rows:
        change_pct = None
        if last_price is not None and prev_close:
            change_pct = (last_price - prev_close) / prev_close * 100
        quotes.append(
            {
                "code": code,
                "name": name,
                "market": market,
                "last_price": last_price,
                "prev_close": prev_close,
                "change_pct": change_pct,
                "volume": volume,
            }
        )

    by_change = sorted(
        (q for q in quotes if q["change_pct"] is not None),
        key=lambda q: abs(q["change_pct"]),
        reverse=True,
    )[:top_change]
    by_volume = sorted(
        (q for q in quotes if q["volume"] is not None),
        key=lambda q: q["volume"],
        reverse=True,
    )[:top_volume]

    watchlist_codes = {w["code"] for w in get_watchlist(conn)}
    position_codes = {p.code for p in get_all_positions(conn)}
    selected_codes = (
        {q["code"] for q in by_change}
        | {q["code"] for q in by_volume}
        | watchlist_codes
        | position_codes
    )

    by_code = {q["code"]: q for q in quotes}
    return sorted(
        (by_code[code] for code in selected_codes if code in by_code),
        key=lambda q: q["code"],
    )


def insert_agent_run(
    conn: sqlite3.Connection,
    candidates: str,
    decisions: str,
    reasoning: str,
    order_ids: str,
) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO agent_runs (ts, candidates, decisions, reasoning, order_ids) VALUES (?, ?, ?, ?, ?)",
        (ts, candidates, decisions, reasoning, order_ids),
    )
    conn.commit()
    return cursor.lastrowid


def get_agent_runs(conn: sqlite3.Connection, since: str | None = None) -> list[dict]:
    if since is None:
        rows = conn.execute(
            "SELECT id, ts, candidates, decisions, reasoning, order_ids FROM agent_runs ORDER BY id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, ts, candidates, decisions, reasoning, order_ids FROM agent_runs WHERE ts >= ? ORDER BY id DESC",
            (since,),
        ).fetchall()
    return [
        {
            "id": r[0],
            "ts": r[1],
            "candidates": r[2],
            "decisions": r[3],
            "reasoning": r[4],
            "order_ids": r[5],
        }
        for r in rows
    ]


def ensure_autonomous_control(conn: sqlite3.Connection, enabled: bool = False) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO autonomous_control (id, enabled, updated_at) VALUES (1, ?, ?)",
        (int(enabled), now),
    )
    conn.commit()


def set_autonomous_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
    ensure_autonomous_control(conn)
    conn.execute(
        "UPDATE autonomous_control SET enabled = ?, updated_at = ? WHERE id = 1",
        (int(enabled), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_autonomous_control(conn: sqlite3.Connection) -> dict:
    ensure_autonomous_control(conn)
    row = conn.execute(
        "SELECT enabled, updated_at FROM autonomous_control WHERE id = 1"
    ).fetchone()
    return {"enabled": bool(row[0]), "updated_at": row[1]}


def insert_autonomous_cycle(
    conn: sqlite3.Connection,
    *,
    started_at: str,
    status: str,
    market_open: bool,
    decisions: str,
    order_ids: str,
    total_value: float | None,
    error: str | None = None,
    market_regime: str | None = None,
    target_exposure_pct: float | None = None,
    blocked_decisions: str = "[]",
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO autonomous_cycles
            (started_at, completed_at, status, market_open, decisions, order_ids,
             total_value, error, market_regime, target_exposure_pct, blocked_decisions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            started_at,
            datetime.now(timezone.utc).isoformat(),
            status,
            int(market_open),
            decisions,
            order_ids,
            total_value,
            error,
            market_regime,
            target_exposure_pct,
            blocked_decisions,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_autonomous_cycles(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, started_at, completed_at, status, market_open, decisions,
               order_ids, total_value, error, market_regime, target_exposure_pct,
               blocked_decisions
        FROM autonomous_cycles ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": row[0],
            "started_at": row[1],
            "completed_at": row[2],
            "status": row[3],
            "market_open": bool(row[4]),
            "decisions": json.loads(row[5]),
            "order_ids": json.loads(row[6]),
            "total_value": row[7],
            "error": row[8],
            "market_regime": row[9],
            "target_exposure_pct": row[10],
            "blocked_decisions": json.loads(row[11] or "[]"),
        }
        for row in rows
    ]
