# Backend Paper Trading API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI backend that provides stock search, watchlist, simulated buy/sell orders, and portfolio/P&L tracking for KOSPI/KOSDAQ stocks, backed by free EOD data (pykrx) and a self-built order simulation engine, with `MarketDataProvider`/`OrderExecutor` abstracted so KIS's real API can be swapped in later without touching callers.

**Architecture:** SQLite-backed FastAPI app. `app/market_data/` defines a `MarketDataProvider` interface with a `PykrxProvider` implementation (EOD ticker master + OHLCV). `app/execution/` defines an `OrderExecutor` interface with a `SimulatedExecutor` that fills orders at latest close price and updates positions/cash through `app/repository.py`. `app/portfolio.py` holds pure position/P&L math with no I/O. REST endpoints in `app/api/` expose stocks, watchlist, orders, and portfolio to the (future) Next.js frontend.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, SQLite (stdlib `sqlite3`), pykrx, pytest, httpx (for `TestClient`), managed with `uv`.

## Global Constraints

- Single user, no login/auth (per spec scope).
- Full KOSPI+KOSDAQ universe must be searchable/tradeable — no artificial ticker subset.
- Stage 1 only: EOD data via pykrx + self-simulated fills at latest close. No real-time quotes, no order book, no KIS calls in this plan (that's stage 2, separate future work).
- `MarketDataProvider` and `OrderExecutor` must be ABCs with swappable implementations — no code outside `app/market_data/` and `app/execution/` may depend on `pykrx` or a specific executor directly.
- Commit message format: `<type>: <description>` (feat/fix/refactor/docs/test/chore), no trailer.
- Files ~200-400 lines typical, 800 max. Split if a file grows past that.
- No mutation of shared state outside the DB layer — `portfolio.py` functions must be pure (take inputs, return new values).

---

## File Structure

```
kis-paper-trading/
  backend/
    pyproject.toml
    app/
      __init__.py
      config.py
      main.py
      portfolio.py              # pure position/P&L math, no I/O
      repository.py              # all SQLite access
      load_market_data.py        # batch loader CLI (stocks + OHLCV)
      market_data/
        __init__.py
        base.py                  # MarketDataProvider ABC, Stock, OhlcvBar
        pykrx_provider.py
      execution/
        __init__.py
        base.py                  # OrderExecutor ABC, OrderResult, OrderExecutionError
        simulated_executor.py
      api/
        __init__.py
        stocks.py
        watchlist.py
        orders.py
        portfolio.py
    tests/
      test_main.py
      test_portfolio.py
      test_repository.py
      test_pykrx_provider.py
      test_simulated_executor.py
      test_load_market_data.py
      test_api_stocks.py
      test_api_watchlist.py
      test_api_orders.py
      test_api_portfolio.py
```

---

### Task 1: Project scaffolding + health check

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/test_main.py`

**Interfaces:**
- Produces: `app.main.app` — the FastAPI instance, importable by all later API tasks and by uvicorn.

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "kis-paper-trading-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pykrx>=1.2.8",
    "httpx>=0.27",
]

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.uv]
package = false
```

- [ ] **Step 2: Install dependencies**

Run: `cd backend && uv sync`
Expected: creates `.venv` and `uv.lock`, no errors.

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/test_main.py
from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` or `ImportError`.

- [ ] **Step 5: Create `backend/app/__init__.py`** (empty file)

- [ ] **Step 6: Create `backend/app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="KIS Paper Trading API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/__init__.py backend/app/main.py backend/tests/test_main.py
git commit -m "feat: scaffold FastAPI backend with health check"
```

---

### Task 2: Pure portfolio math (`app/portfolio.py`)

**Files:**
- Create: `backend/app/portfolio.py`
- Test: `backend/tests/test_portfolio.py`

**Interfaces:**
- Produces: `Position` dataclass (`code: str`, `quantity: int`, `avg_price: float`); `apply_buy_fill(existing: Position | None, code: str, quantity: int, price: float) -> Position`; `apply_sell_fill(existing: Position, quantity: int, price: float) -> tuple[Position | None, float]`; `compute_portfolio_value(cash: float, positions: list[Position], current_prices: dict[str, float]) -> dict`.
- Consumes: nothing (pure module, no dependencies on other app code).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_portfolio.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_portfolio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.portfolio'`.

- [ ] **Step 3: Write `backend/app/portfolio.py`**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    code: str
    quantity: int
    avg_price: float


def apply_buy_fill(
    existing: Position | None, code: str, quantity: int, price: float
) -> Position:
    if existing is None:
        return Position(code=code, quantity=quantity, avg_price=price)
    total_cost = existing.avg_price * existing.quantity + price * quantity
    total_quantity = existing.quantity + quantity
    return Position(code=code, quantity=total_quantity, avg_price=total_cost / total_quantity)


def apply_sell_fill(
    existing: Position, quantity: int, price: float
) -> tuple[Position | None, float]:
    if quantity > existing.quantity:
        raise ValueError("cannot sell more than held quantity")
    realized_pnl = (price - existing.avg_price) * quantity
    remaining = existing.quantity - quantity
    if remaining == 0:
        return None, realized_pnl
    return Position(code=existing.code, quantity=remaining, avg_price=existing.avg_price), realized_pnl


def compute_portfolio_value(
    cash: float, positions: list[Position], current_prices: dict[str, float]
) -> dict:
    evaluated_value = sum(current_prices[p.code] * p.quantity for p in positions)
    cost_basis = sum(p.avg_price * p.quantity for p in positions)
    return {
        "cash": cash,
        "evaluated_value": evaluated_value,
        "total_value": cash + evaluated_value,
        "unrealized_pnl": evaluated_value - cost_basis,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_portfolio.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/portfolio.py backend/tests/test_portfolio.py
git commit -m "feat: add pure portfolio position and P&L math"
```

---

### Task 3: SQLite schema + repository (accounts, positions, orders, snapshots)

**Files:**
- Create: `backend/app/repository.py`
- Test: `backend/tests/test_repository.py`

**Interfaces:**
- Consumes: `app.portfolio.Position`, `apply_buy_fill`, `apply_sell_fill` (Task 2).
- Produces: `init_db(conn, initial_capital=10_000_000.0) -> None`; `get_cash_balance(conn) -> float`; `get_position(conn, code) -> Position | None`; `get_all_positions(conn) -> list[Position]`; `apply_buy(conn, code, quantity, price) -> None`; `apply_sell(conn, code, quantity, price) -> float`; `record_order(conn, code, side, quantity, price) -> int`; `get_orders(conn) -> list[dict]`; `insert_snapshot(conn, total_value, cash, evaluated_value, pnl) -> None`; `get_snapshots(conn) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_repository.py
import sqlite3

import pytest

from app import repository


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    repository.init_db(connection, initial_capital=1_000_000.0)
    yield connection
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.repository'`.

- [ ] **Step 3: Write `backend/app/repository.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_repository.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/repository.py backend/tests/test_repository.py
git commit -m "feat: add SQLite schema and account/position/order repository"
```

---

### Task 4: Stock master, price history, watchlist repository functions

**Files:**
- Modify: `backend/app/repository.py` (append functions)
- Test: `backend/tests/test_repository.py` (append tests)

**Interfaces:**
- Consumes: `app.market_data.base.Stock`, `app.market_data.base.OhlcvBar` (Task 5 — this task defines the repository functions that accept them; Task 5 defines the dataclasses. Since Task 5 hasn't run yet, this task defines its own minimal duck-typed access: any object with `.code`, `.name`, `.market` for stocks and `.date`, `.open`, `.high`, `.low`, `.close`, `.volume` for bars — Task 5's dataclasses satisfy this shape).
- Produces: `upsert_stocks(conn, stocks) -> None`; `search_stocks(conn, query) -> list[dict]`; `upsert_price_history(conn, code, bars) -> None`; `get_price_history(conn, code) -> list[dict]`; `add_watchlist(conn, code) -> None`; `remove_watchlist(conn, code) -> None`; `get_watchlist(conn) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_repository.py
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
    assert results == [{"code": "005930", "name": "삼성전자", "market": "KOSPI"}]


def test_upsert_stocks_updates_existing_row(conn):
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="old", market="KOSPI")])
    repository.upsert_stocks(conn, [_FakeStock(code="005930", name="삼성전자", market="KOSPI")])
    results = repository.search_stocks(conn, "005930")
    assert results == [{"code": "005930", "name": "삼성전자", "market": "KOSPI"}]


def test_upsert_and_get_price_history(conn):
    bar = _FakeBar(date="2026-08-27", open=70000, high=71000, low=69500, close=70500, volume=1_000_000)
    repository.upsert_price_history(conn, "005930", [bar])
    history = repository.get_price_history(conn, "005930")
    assert history == [
        {"date": "2026-08-27", "open": 70000, "high": 71000, "low": 69500, "close": 70500, "volume": 1_000_000}
    ]


def test_watchlist_add_remove_and_list(conn):
    repository.add_watchlist(conn, "005930")
    repository.add_watchlist(conn, "000660")
    assert repository.get_watchlist(conn) == ["000660", "005930"]
    repository.remove_watchlist(conn, "000660")
    assert repository.get_watchlist(conn) == ["005930"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_repository.py -v`
Expected: FAIL with `AttributeError: module 'app.repository' has no attribute 'upsert_stocks'`.

- [ ] **Step 3: Append to `backend/app/repository.py`**

```python
def upsert_stocks(conn: sqlite3.Connection, stocks: list) -> None:
    conn.executemany(
        "INSERT INTO stocks (code, name, market) VALUES (?, ?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name = excluded.name, market = excluded.market",
        [(s.code, s.name, s.market) for s in stocks],
    )
    conn.commit()


def search_stocks(conn: sqlite3.Connection, query: str) -> list[dict]:
    like = f"%{query}%"
    rows = conn.execute(
        "SELECT code, name, market FROM stocks WHERE code LIKE ? OR name LIKE ? ORDER BY code",
        (like, like),
    ).fetchall()
    return [{"code": r[0], "name": r[1], "market": r[2]} for r in rows]


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


def get_watchlist(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT code FROM watchlist ORDER BY code").fetchall()
    return [r[0] for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_repository.py -v`
Expected: PASS (11 tests total)

- [ ] **Step 5: Commit**

```bash
git add backend/app/repository.py backend/tests/test_repository.py
git commit -m "feat: add stock master, price history, and watchlist repository functions"
```

---

### Task 5: `MarketDataProvider` interface + `PykrxProvider`

**Files:**
- Create: `backend/app/market_data/__init__.py` (empty)
- Create: `backend/app/market_data/base.py`
- Create: `backend/app/market_data/pykrx_provider.py`
- Test: `backend/tests/test_pykrx_provider.py`

**Interfaces:**
- Produces: `Stock` dataclass (`code`, `name`, `market`); `OhlcvBar` dataclass (`date`, `open`, `high`, `low`, `close`, `volume`); `MarketDataProvider` ABC with `get_ticker_master() -> list[Stock]`, `get_ohlcv(code, start, end) -> list[OhlcvBar]`, `get_latest_price(code) -> float`; `PykrxProvider` implementing all three.

- [ ] **Step 1: Write `backend/app/market_data/base.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    market: str


@dataclass(frozen=True)
class OhlcvBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketDataProvider(ABC):
    @abstractmethod
    def get_ticker_master(self) -> list[Stock]:
        ...

    @abstractmethod
    def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
        ...

    @abstractmethod
    def get_latest_price(self, code: str) -> float:
        ...
```

- [ ] **Step 2: Create `backend/app/market_data/__init__.py`** (empty file)

- [ ] **Step 3: Write the failing test (uses monkeypatch, no real network calls)**

```python
# backend/tests/test_pykrx_provider.py
import pandas as pd
import pytest

from app.market_data.pykrx_provider import PykrxProvider


def test_get_ticker_master_returns_stocks_from_both_markets(monkeypatch):
    def fake_get_market_ticker_list(date, market):
        return {"KOSPI": ["005930"], "KOSDAQ": ["247540"]}[market]

    def fake_get_market_ticker_name(code):
        return {"005930": "삼성전자", "247540": "에코프로비엠"}[code]

    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ticker_list",
        fake_get_market_ticker_list,
    )
    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ticker_name",
        fake_get_market_ticker_name,
    )

    provider = PykrxProvider()
    stocks = provider.get_ticker_master()

    assert {(s.code, s.name, s.market) for s in stocks} == {
        ("005930", "삼성전자", "KOSPI"),
        ("247540", "에코프로비엠", "KOSDAQ"),
    }


def test_get_ohlcv_maps_korean_columns_to_ohlcv_bar(monkeypatch):
    df = pd.DataFrame(
        {"시가": [70000], "고가": [71000], "저가": [69500], "종가": [70500], "거래량": [1_000_000]},
        index=pd.to_datetime(["2026-08-27"]),
    )

    def fake_get_market_ohlcv(start, end, code):
        return df

    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ohlcv",
        fake_get_market_ohlcv,
    )

    provider = PykrxProvider()
    bars = provider.get_ohlcv("005930", "20260801", "20260827")

    assert len(bars) == 1
    assert bars[0].date == "2026-08-27"
    assert bars[0].close == 70500.0
    assert bars[0].volume == 1_000_000


def test_get_latest_price_returns_most_recent_close(monkeypatch):
    df = pd.DataFrame(
        {"시가": [70000, 71000], "고가": [71000, 72000], "저가": [69500, 70500],
         "종가": [70500, 71500], "거래량": [1_000_000, 900_000]},
        index=pd.to_datetime(["2026-08-26", "2026-08-27"]),
    )

    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ohlcv",
        lambda start, end, code: df,
    )

    provider = PykrxProvider()
    assert provider.get_latest_price("005930") == 71500.0


def test_get_latest_price_raises_when_no_data(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.pykrx_provider.pykrx_stock.get_market_ohlcv",
        lambda start, end, code: pd.DataFrame(),
    )

    provider = PykrxProvider()
    with pytest.raises(ValueError):
        provider.get_latest_price("005930")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_pykrx_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.market_data.pykrx_provider'`.

- [ ] **Step 5: Write `backend/app/market_data/pykrx_provider.py`**

```python
from datetime import datetime, timedelta

from pykrx import stock as pykrx_stock

from .base import MarketDataProvider, OhlcvBar, Stock


class PykrxProvider(MarketDataProvider):
    def get_ticker_master(self) -> list[Stock]:
        today = datetime.now().strftime("%Y%m%d")
        result = []
        for market in ("KOSPI", "KOSDAQ"):
            codes = pykrx_stock.get_market_ticker_list(today, market=market)
            for code in codes:
                name = pykrx_stock.get_market_ticker_name(code)
                result.append(Stock(code=code, name=name, market=market))
        return result

    def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
        df = pykrx_stock.get_market_ohlcv(start, end, code)
        bars = []
        for idx, row in df.iterrows():
            bars.append(
                OhlcvBar(
                    date=idx.strftime("%Y-%m-%d"),
                    open=float(row["시가"]),
                    high=float(row["고가"]),
                    low=float(row["저가"]),
                    close=float(row["종가"]),
                    volume=int(row["거래량"]),
                )
            )
        return bars

    def get_latest_price(self, code: str) -> float:
        end = datetime.now()
        start = end - timedelta(days=10)
        bars = self.get_ohlcv(code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        if not bars:
            raise ValueError(f"no price data available for {code}")
        return bars[-1].close
```

- [ ] **Step 6: Add `pandas` as an explicit test dependency and sync**

`pandas` arrives transitively via `pykrx`, but the test imports it directly, so add it explicitly:

```toml
# in backend/pyproject.toml, add to [dependency-groups] dev
dev = ["pytest>=8.0", "pandas>=2.0"]
```

Run: `cd backend && uv sync`

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_pykrx_provider.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/market_data/ backend/tests/test_pykrx_provider.py
git commit -m "feat: add MarketDataProvider interface and PykrxProvider"
```

---

### Task 6: `OrderExecutor` interface + `SimulatedExecutor`

**Files:**
- Create: `backend/app/execution/__init__.py` (empty)
- Create: `backend/app/execution/base.py`
- Create: `backend/app/execution/simulated_executor.py`
- Test: `backend/tests/test_simulated_executor.py`

**Interfaces:**
- Consumes: `app.market_data.base.MarketDataProvider` (Task 5); `app.repository.get_cash_balance`, `get_position`, `apply_buy`, `apply_sell`, `record_order`, `init_db` (Task 3).
- Produces: `OrderResult` dataclass (`order_id`, `code`, `side`, `quantity`, `fill_price`); `OrderExecutionError` exception; `OrderExecutor` ABC with `place_order(code, side, quantity) -> OrderResult`; `SimulatedExecutor(provider, conn)` implementing it.

- [ ] **Step 1: Write `backend/app/execution/base.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderResult:
    order_id: int
    code: str
    side: str
    quantity: int
    fill_price: float


class OrderExecutionError(Exception):
    pass


class OrderExecutor(ABC):
    @abstractmethod
    def place_order(self, code: str, side: str, quantity: int) -> OrderResult:
        ...
```

- [ ] **Step 2: Create `backend/app/execution/__init__.py`** (empty file)

- [ ] **Step 3: Write the failing tests**

```python
# backend/tests/test_simulated_executor.py
import sqlite3

import pytest

from app import repository
from app.execution.base import OrderExecutionError
from app.execution.simulated_executor import SimulatedExecutor


class _FakeProvider:
    def __init__(self, price: float):
        self.price = price

    def get_latest_price(self, code: str) -> float:
        return self.price


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    repository.init_db(connection, initial_capital=1_000_000.0)
    yield connection
    connection.close()


def test_place_buy_order_fills_at_latest_price(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    result = executor.place_order("005930", "buy", 10)

    assert result.fill_price == 70000.0
    assert result.side == "buy"
    position = repository.get_position(conn, "005930")
    assert position.quantity == 10
    assert repository.get_cash_balance(conn) == 300_000.0


def test_place_sell_order_without_position_raises(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    with pytest.raises(OrderExecutionError):
        executor.place_order("005930", "sell", 1)


def test_place_buy_order_exceeding_cash_raises(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    with pytest.raises(OrderExecutionError):
        executor.place_order("005930", "buy", 1000)


def test_place_order_rejects_invalid_side(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    with pytest.raises(OrderExecutionError):
        executor.place_order("005930", "hold", 1)


def test_place_order_rejects_non_positive_quantity(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    with pytest.raises(OrderExecutionError):
        executor.place_order("005930", "buy", 0)


def test_place_sell_order_records_order_history(conn):
    executor = SimulatedExecutor(_FakeProvider(70000.0), conn)
    executor.place_order("005930", "buy", 10)
    executor.place_order("005930", "sell", 4)

    orders = repository.get_orders(conn)
    assert len(orders) == 2
    assert orders[0]["side"] == "sell"
    assert orders[0]["quantity"] == 4
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_simulated_executor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.execution.simulated_executor'`.

- [ ] **Step 5: Write `backend/app/execution/simulated_executor.py`**

```python
from .. import repository
from ..market_data.base import MarketDataProvider
from .base import OrderExecutionError, OrderExecutor, OrderResult


class SimulatedExecutor(OrderExecutor):
    def __init__(self, provider: MarketDataProvider, conn):
        self.provider = provider
        self.conn = conn

    def place_order(self, code: str, side: str, quantity: int) -> OrderResult:
        if side not in ("buy", "sell"):
            raise OrderExecutionError(f"invalid side: {side}")
        if quantity <= 0:
            raise OrderExecutionError("quantity must be positive")

        price = self.provider.get_latest_price(code)

        if side == "buy":
            cash = repository.get_cash_balance(self.conn)
            cost = price * quantity
            if cost > cash:
                raise OrderExecutionError("insufficient cash balance")
            repository.apply_buy(self.conn, code, quantity, price)
        else:
            position = repository.get_position(self.conn, code)
            if position is None or position.quantity < quantity:
                raise OrderExecutionError("insufficient position quantity")
            repository.apply_sell(self.conn, code, quantity, price)

        order_id = repository.record_order(self.conn, code, side, quantity, price)
        return OrderResult(order_id=order_id, code=code, side=side, quantity=quantity, fill_price=price)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_simulated_executor.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/execution/ backend/tests/test_simulated_executor.py
git commit -m "feat: add OrderExecutor interface and SimulatedExecutor"
```

---

### Task 7: Batch market data loader (`app/load_market_data.py`)

**Files:**
- Create: `backend/app/load_market_data.py`
- Test: `backend/tests/test_load_market_data.py`

**Interfaces:**
- Consumes: `app.market_data.base.MarketDataProvider`, `Stock`, `OhlcvBar` (Task 5); `app.repository.upsert_stocks`, `upsert_price_history`, `init_db` (Tasks 3-4); `app.market_data.pykrx_provider.PykrxProvider` (Task 5).
- Produces: `load_all(conn, provider, lookback_days=90) -> int` (returns number of stocks loaded); `main()` CLI entrypoint.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_load_market_data.py
import sqlite3

from app import repository
from app.load_market_data import load_all
from app.market_data.base import OhlcvBar, Stock


class _FakeProvider:
    def get_ticker_master(self) -> list[Stock]:
        return [Stock(code="005930", name="삼성전자", market="KOSPI")]

    def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
        return [
            OhlcvBar(date="2026-08-27", open=70000, high=71000, low=69500, close=70500, volume=1_000_000)
        ]

    def get_latest_price(self, code: str) -> float:
        return 70500.0


def test_load_all_inserts_stocks_and_price_history():
    conn = sqlite3.connect(":memory:")
    repository.init_db(conn)

    count = load_all(conn, _FakeProvider())

    assert count == 1
    stocks = repository.search_stocks(conn, "005930")
    assert stocks == [{"code": "005930", "name": "삼성전자", "market": "KOSPI"}]
    history = repository.get_price_history(conn, "005930")
    assert len(history) == 1
    assert history[0]["close"] == 70500


def test_load_all_skips_stocks_with_no_bars():
    class _EmptyBarsProvider(_FakeProvider):
        def get_ohlcv(self, code: str, start: str, end: str) -> list[OhlcvBar]:
            return []

    conn = sqlite3.connect(":memory:")
    repository.init_db(conn)

    count = load_all(conn, _EmptyBarsProvider())

    assert count == 1
    assert repository.get_price_history(conn, "005930") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_load_market_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.load_market_data'`.

- [ ] **Step 3: Write `backend/app/load_market_data.py`**

```python
import argparse
import sqlite3
from datetime import datetime, timedelta

from . import repository
from .market_data.base import MarketDataProvider
from .market_data.pykrx_provider import PykrxProvider


def load_all(conn: sqlite3.Connection, provider: MarketDataProvider, lookback_days: int = 90) -> int:
    stocks = provider.get_ticker_master()
    repository.upsert_stocks(conn, stocks)

    end = datetime.now()
    start = end - timedelta(days=lookback_days)

    for stock in stocks:
        bars = provider.get_ohlcv(stock.code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        if bars:
            repository.upsert_price_history(conn, stock.code, bars)

    return len(stocks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load KOSPI/KOSDAQ market data via pykrx")
    parser.add_argument("--db-path", default="kis_paper_trading.db")
    parser.add_argument("--lookback-days", type=int, default=90)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    repository.init_db(conn)
    count = load_all(conn, PykrxProvider(), args.lookback_days)
    print(f"loaded {count} stocks")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_load_market_data.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/load_market_data.py backend/tests/test_load_market_data.py
git commit -m "feat: add batch market data loader CLI"
```

---

### Task 8: Config module + wiring providers/executor into the FastAPI app lifespan

**Files:**
- Create: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_main.py` (append)

**Interfaces:**
- Consumes: `app.repository.init_db` (Task 3); `app.market_data.pykrx_provider.PykrxProvider` (Task 5); `app.execution.simulated_executor.SimulatedExecutor` (Task 6).
- Produces: `Settings` dataclass (`db_path`, `initial_capital`, `market_data_provider`, `order_executor`); `load_settings() -> Settings`. `app.state.conn`, `app.state.provider`, `app.state.executor` populated on startup via lifespan, readable by later API tasks through `request.app.state`.

- [ ] **Step 1: Write `backend/app/config.py`**

```python
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str
    initial_capital: float
    market_data_provider: str
    order_executor: str


def load_settings() -> Settings:
    return Settings(
        db_path=os.environ.get("DB_PATH", "kis_paper_trading.db"),
        initial_capital=float(os.environ.get("INITIAL_CAPITAL", "10000000")),
        market_data_provider=os.environ.get("MARKET_DATA_PROVIDER", "pykrx"),
        order_executor=os.environ.get("ORDER_EXECUTOR", "simulated"),
    )
```

- [ ] **Step 2: Write the failing test (verifies lifespan wires state correctly)**

```python
# append to backend/tests/test_main.py
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_lifespan_wires_conn_provider_executor(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "500000")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        assert isinstance(client.app.state.provider, PykrxProvider)
        assert client.app.state.executor is not None
        response = client.get("/health")
        assert response.status_code == 200
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_main.py -v`
Expected: FAIL with `AttributeError: 'State' object has no attribute 'provider'`.

- [ ] **Step 4: Rewrite `backend/app/main.py`**

```python
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import repository
from .config import load_settings
from .execution.simulated_executor import SimulatedExecutor
from .market_data.pykrx_provider import PykrxProvider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    repository.init_db(conn, settings.initial_capital)

    if settings.market_data_provider != "pykrx":
        raise ValueError(f"unknown market data provider: {settings.market_data_provider}")
    provider = PykrxProvider()

    if settings.order_executor != "simulated":
        raise ValueError(f"unknown order executor: {settings.order_executor}")
    executor = SimulatedExecutor(provider, conn)

    app.state.conn = conn
    app.state.provider = provider
    app.state.executor = executor
    yield
    conn.close()


app = FastAPI(title="KIS Paper Trading API", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_main.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/main.py backend/tests/test_main.py
git commit -m "feat: wire provider and executor into FastAPI lifespan via config"
```

---

### Task 9: Stock search + watchlist REST endpoints

**Files:**
- Create: `backend/app/api/__init__.py` (empty)
- Create: `backend/app/api/stocks.py`
- Create: `backend/app/api/watchlist.py`
- Modify: `backend/app/main.py` (include routers)
- Test: `backend/tests/test_api_stocks.py`
- Test: `backend/tests/test_api_watchlist.py`

**Interfaces:**
- Consumes: `app.repository.search_stocks`, `get_price_history`, `add_watchlist`, `remove_watchlist`, `get_watchlist` (Tasks 3-4); `request.app.state.conn` (Task 8).
- Produces: `router` (`APIRouter`) exported from both `app/api/stocks.py` and `app/api/watchlist.py`, included into `app.main.app`.

- [ ] **Step 1: Write `backend/app/api/stocks.py`**

```python
from fastapi import APIRouter, Query, Request

from .. import repository

router = APIRouter()


@router.get("/stocks")
def search_stocks(request: Request, q: str = Query(default="")):
    return repository.search_stocks(request.app.state.conn, q)


@router.get("/stocks/{code}/history")
def stock_history(code: str, request: Request):
    return repository.get_price_history(request.app.state.conn, code)
```

- [ ] **Step 2: Write `backend/app/api/watchlist.py`**

```python
from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import repository

router = APIRouter()


class WatchlistRequest(BaseModel):
    code: str


@router.get("/watchlist")
def list_watchlist(request: Request):
    return repository.get_watchlist(request.app.state.conn)


@router.post("/watchlist")
def add_watchlist(req: WatchlistRequest, request: Request):
    repository.add_watchlist(request.app.state.conn, req.code)
    return {"code": req.code}


@router.delete("/watchlist/{code}")
def remove_watchlist(code: str, request: Request):
    repository.remove_watchlist(request.app.state.conn, code)
    return {"code": code}
```

- [ ] **Step 3: Create `backend/app/api/__init__.py`** (empty file)

- [ ] **Step 4: Write the failing tests**

```python
# backend/tests/test_api_stocks.py
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_search_stocks_and_get_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.get("/stocks", params={"q": "005930"})
        assert response.status_code == 200
        assert response.json() == []

        response = client.get("/stocks/005930/history")
        assert response.status_code == 200
        assert response.json() == []
```

```python
# backend/tests/test_api_watchlist.py
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_watchlist_add_list_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.post("/watchlist", json={"code": "005930"})
        assert response.status_code == 200

        response = client.get("/watchlist")
        assert response.status_code == 200
        assert response.json() == ["005930"]

        response = client.delete("/watchlist/005930")
        assert response.status_code == 200

        response = client.get("/watchlist")
        assert response.json() == []
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_api_stocks.py tests/test_api_watchlist.py -v`
Expected: FAIL with `404 Not Found` (routes not registered yet).

- [ ] **Step 6: Include routers in `backend/app/main.py`**

Add near the top imports and after `app = FastAPI(...)`:

```python
from .api import stocks, watchlist
```

```python
app.include_router(stocks.router)
app.include_router(watchlist.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_api_stocks.py tests/test_api_watchlist.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/__init__.py backend/app/api/stocks.py backend/app/api/watchlist.py backend/app/main.py backend/tests/test_api_stocks.py backend/tests/test_api_watchlist.py
git commit -m "feat: add stock search, history, and watchlist REST endpoints"
```

---

### Task 10: Order + portfolio REST endpoints

**Files:**
- Create: `backend/app/api/orders.py`
- Create: `backend/app/api/portfolio.py`
- Modify: `backend/app/main.py` (include routers)
- Test: `backend/tests/test_api_orders.py`
- Test: `backend/tests/test_api_portfolio.py`

**Interfaces:**
- Consumes: `app.repository.get_orders`, `get_cash_balance`, `get_all_positions`, `get_snapshots` (Tasks 3-4); `app.portfolio.compute_portfolio_value` (Task 2); `app.execution.base.OrderExecutionError` (Task 6); `request.app.state.executor`, `request.app.state.provider`, `request.app.state.conn` (Task 8).
- Produces: `router` from both modules, included into `app.main.app`.

- [ ] **Step 1: Write `backend/app/api/orders.py`**

```python
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import repository
from ..execution.base import OrderExecutionError

router = APIRouter()


class OrderRequest(BaseModel):
    code: str
    side: str
    quantity: int


@router.post("/orders")
def create_order(req: OrderRequest, request: Request):
    try:
        result = request.app.state.executor.place_order(req.code, req.side, req.quantity)
    except OrderExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "order_id": result.order_id,
        "code": result.code,
        "side": result.side,
        "quantity": result.quantity,
        "fill_price": result.fill_price,
    }


@router.get("/orders")
def list_orders(request: Request):
    return repository.get_orders(request.app.state.conn)
```

- [ ] **Step 2: Write `backend/app/api/portfolio.py`**

```python
from fastapi import APIRouter, Request

from .. import repository
from ..portfolio import compute_portfolio_value

router = APIRouter()


@router.get("/portfolio")
def get_portfolio(request: Request):
    conn = request.app.state.conn
    provider = request.app.state.provider
    cash = repository.get_cash_balance(conn)
    positions = repository.get_all_positions(conn)
    current_prices = {p.code: provider.get_latest_price(p.code) for p in positions}
    value = compute_portfolio_value(cash, positions, current_prices)
    return {
        **value,
        "positions": [
            {"code": p.code, "quantity": p.quantity, "avg_price": p.avg_price} for p in positions
        ],
    }


@router.get("/portfolio/history")
def get_portfolio_history(request: Request):
    return repository.get_snapshots(request.app.state.conn)
```

- [ ] **Step 3: Write the failing tests**

```python
# backend/tests/test_api_orders.py
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_create_order_then_list_orders(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "1000000")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.post("/orders", json={"code": "005930", "side": "buy", "quantity": 10})
        assert response.status_code == 200
        assert response.json()["fill_price"] == 1000.0

        response = client.get("/orders")
        assert response.status_code == 200
        assert len(response.json()) == 1


def test_create_order_insufficient_cash_returns_400(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "100")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.post("/orders", json={"code": "005930", "side": "buy", "quantity": 10})
        assert response.status_code == 400
```

```python
# backend/tests/test_api_portfolio.py
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.pykrx_provider import PykrxProvider


def test_portfolio_reflects_filled_order(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "1000000")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        client.post("/orders", json={"code": "005930", "side": "buy", "quantity": 10})

        response = client.get("/portfolio")
        assert response.status_code == 200
        body = response.json()
        assert body["cash"] == 990_000.0
        assert body["evaluated_value"] == 10_000.0
        assert body["positions"] == [{"code": "005930", "quantity": 10, "avg_price": 1000.0}]


def test_portfolio_history_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.get("/portfolio/history")
        assert response.status_code == 200
        assert response.json() == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_api_orders.py tests/test_api_portfolio.py -v`
Expected: FAIL with `404 Not Found`.

- [ ] **Step 5: Include routers in `backend/app/main.py`**

Update the import line from Task 9 to:

```python
from .api import orders, portfolio, stocks, watchlist
```

Add alongside the existing `include_router` calls:

```python
app.include_router(orders.router)
app.include_router(portfolio.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_api_orders.py tests/test_api_portfolio.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Run the full test suite**

Run: `cd backend && uv run pytest tests/ -v`
Expected: PASS (all tests across all tasks — 30+ tests)

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/orders.py backend/app/api/portfolio.py backend/app/main.py backend/tests/test_api_orders.py backend/tests/test_api_portfolio.py
git commit -m "feat: add order placement and portfolio REST endpoints"
```

---

## After This Plan

- Run `cd backend && uv run python -m app.load_market_data` once to populate the stock master + price history before using the API for real.
- Run the dev server with `cd backend && uv run uvicorn app.main:app --reload` (defaults to `http://127.0.0.1:8000`).
- Next planning step: a separate frontend plan (Next.js dashboard) consuming this API — not covered here.
- Future stage-2 plan (after KIS account/keys are ready): add `KisProvider` and `KisPaperExecutor` implementations alongside the existing ones, switch via `MARKET_DATA_PROVIDER=kis` / `ORDER_EXECUTOR=kis`, add a periodic snapshot job calling `repository.insert_snapshot`.
