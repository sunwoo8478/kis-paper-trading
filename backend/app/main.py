import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import repository
from .api import agent, orders, portfolio, stocks, watchlist
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

app.include_router(agent.router)
app.include_router(orders.router)
app.include_router(portfolio.router)
app.include_router(stocks.router)
app.include_router(watchlist.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
