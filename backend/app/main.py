import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import repository
from .ai.autonomous import AutonomousTradingEngine
from .api import agent, alerts, analytics, journal, kis, market, news, orders, portfolio, stocks, watchlist
from .config import load_settings
from .execution.simulated_executor import SimulatedExecutor
from .integrations.kis import KisPaperClient
from .market_data.naver_provider import NaverRealtimeProvider
from .market_data.pykrx_provider import PykrxProvider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    repository.init_db(conn, settings.initial_capital)

    if settings.market_data_provider == "pykrx":
        provider = PykrxProvider()
    elif settings.market_data_provider == "naver_realtime":
        provider = NaverRealtimeProvider()
    else:
        raise ValueError(f"unknown market data provider: {settings.market_data_provider}")

    if settings.order_executor != "simulated":
        raise ValueError(f"unknown order executor: {settings.order_executor}")
    executor = SimulatedExecutor(provider, conn)

    app.state.conn = conn
    app.state.provider = provider
    app.state.executor = executor
    app.state.kis_client = KisPaperClient()
    autonomous_engine = AutonomousTradingEngine(settings.db_path, provider)
    app.state.autonomous_engine = autonomous_engine
    autonomous_engine.start()
    yield
    autonomous_engine.stop()
    conn.close()


app = FastAPI(title="KIS Paper Trading API", lifespan=lifespan)

app.include_router(agent.router)
app.include_router(alerts.router)
app.include_router(analytics.router)
app.include_router(journal.router)
app.include_router(kis.router)
app.include_router(market.router)
app.include_router(news.router)
app.include_router(orders.router)
app.include_router(portfolio.router)
app.include_router(stocks.router)
app.include_router(watchlist.router)


@app.get("/health")
def health() -> dict:
    engine = app.state.autonomous_engine
    runtime = engine.status()
    kis_status = app.state.kis_client.status()
    return {
        "status": "degraded" if runtime["last_error"] else "ok",
        "database": "connected",
        "kis_paper": {
            "configured": kis_status["configured"],
            "authenticated": kis_status["authenticated"],
            "account_configured": kis_status["account_configured"],
            "order_enabled": kis_status["order_enabled"],
        },
        "autonomous": {
            "enabled": runtime["enabled"],
            "running": runtime["running"],
            "phase": runtime["phase"],
            "last_cycle_at": runtime["last_cycle_at"],
            "last_error": runtime["last_error"],
        },
    }
