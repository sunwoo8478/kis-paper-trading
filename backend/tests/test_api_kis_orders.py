import sqlite3

from fastapi.testclient import TestClient

from app import repository
from app.main import app
from app.market_data.base import Stock


class _Client:
    def __init__(self, order_enabled=True):
        self.order_enabled = order_enabled
        self.orders = []

    def status(self):
        return {
            "configured": True,
            "authenticated": True,
            "account_configured": True,
            "order_enabled": self.order_enabled,
        }

    def place_cash_order(self, code, side, quantity, order_type, limit_price):
        if not self.order_enabled:
            from app.integrations.kis import KisApiError
            raise KisApiError("KIS 모의투자 주문 전송이 잠겨 있습니다")
        self.orders.append({"code": code, "side": side, "quantity": quantity})
        return {"broker_order_id": str(10000 + len(self.orders)), "status": "submitted"}


def _seed(db_path):
    conn = sqlite3.connect(db_path)
    repository.init_db(conn)
    repository.upsert_stocks(conn, [Stock("005930", "삼성전자", "KOSPI")])
    conn.close()


def test_kis_place_order_executes_via_executor(tmp_path, monkeypatch):
    db_path = str(tmp_path / "orders.db")
    monkeypatch.setenv("DB_PATH", db_path)
    _seed(db_path)

    with TestClient(app) as client:
        app.state.kis_client = _Client()
        response = client.post("/kis/orders", json={"code": "005930", "side": "buy", "quantity": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["broker_order_id"] == "10001"
    assert body["code"] == "005930"
    assert body["side"] == "buy"


def test_kis_place_order_rejects_when_locked(tmp_path, monkeypatch):
    db_path = str(tmp_path / "locked-orders.db")
    monkeypatch.setenv("DB_PATH", db_path)
    _seed(db_path)

    with TestClient(app) as client:
        app.state.kis_client = _Client(order_enabled=False)
        response = client.post("/kis/orders", json={"code": "005930", "side": "buy", "quantity": 1})

    assert response.status_code == 400


def test_kis_chat_parses_buy_command_into_proposal(tmp_path, monkeypatch):
    db_path = str(tmp_path / "chat-buy.db")
    monkeypatch.setenv("DB_PATH", db_path)
    _seed(db_path)

    with TestClient(app) as client:
        response = client.post("/kis/chat", json={"prompt": "삼성전자 10주 사줘"})

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"] == {"code": "005930", "name": "삼성전자", "side": "buy", "quantity": 10}


def test_kis_chat_parses_sell_command_into_proposal(tmp_path, monkeypatch):
    db_path = str(tmp_path / "chat-sell.db")
    monkeypatch.setenv("DB_PATH", db_path)
    _seed(db_path)

    with TestClient(app) as client:
        response = client.post("/kis/chat", json={"prompt": "삼성전자 3주 팔아줘"})

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"] == {"code": "005930", "name": "삼성전자", "side": "sell", "quantity": 3}


def test_kis_chat_returns_no_proposal_when_unclear(tmp_path, monkeypatch):
    db_path = str(tmp_path / "chat-unclear.db")
    monkeypatch.setenv("DB_PATH", db_path)
    _seed(db_path)

    with TestClient(app) as client:
        response = client.post("/kis/chat", json={"prompt": "지금 시장 어때?"})

    assert response.status_code == 200
    assert response.json()["proposal"] is None
