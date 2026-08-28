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
