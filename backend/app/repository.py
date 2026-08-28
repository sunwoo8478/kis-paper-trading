import sqlite3
from datetime import datetime, timezone

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
    status TEXT NOT NULL
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
"""


def init_db(conn: sqlite3.Connection, initial_capital: float = 10_000_000.0) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO account (id, cash_balance, initial_capital) VALUES (1, ?, ?)",
        (initial_capital, initial_capital),
    )
    conn.commit()


def get_cash_balance(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT cash_balance FROM account WHERE id = 1").fetchone()
    return row[0]


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


def apply_buy(conn: sqlite3.Connection, code: str, quantity: int, price: float) -> None:
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
    conn.commit()


def apply_sell(conn: sqlite3.Connection, code: str, quantity: int, price: float) -> float:
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
    conn.commit()
    return realized_pnl


def record_order(conn: sqlite3.Connection, code: str, side: str, quantity: int, price: float) -> int:
    filled_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO orders (code, side, quantity, price, filled_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        (code, side, quantity, price, filled_at, "filled"),
    )
    conn.commit()
    return cursor.lastrowid


def get_orders(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, code, side, quantity, price, filled_at, status FROM orders ORDER BY id DESC"
    ).fetchall()
    return [
        {
            "id": r[0], "code": r[1], "side": r[2], "quantity": r[3],
            "price": r[4], "filled_at": r[5], "status": r[6],
        }
        for r in rows
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


def get_snapshots(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, total_value, cash, evaluated_value, pnl FROM portfolio_snapshots ORDER BY ts"
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


def get_agent_runs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts, candidates, decisions, reasoning, order_ids FROM agent_runs ORDER BY id DESC"
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
