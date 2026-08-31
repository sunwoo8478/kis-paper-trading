import json

from fastapi.testclient import TestClient

from app.main import app


def test_agent_status_is_locked_without_model(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)

    with TestClient(app) as client:
        response = client.get("/agent/status")

    assert response.status_code == 200
    assert response.json()["model_connected"] is False
    assert response.json()["execution_mode"] == "observe"
    assert response.json()["auto_execution_enabled"] is False


def test_agent_status_exposes_configured_paper_auto_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "trading-model")
    monkeypatch.setenv("AI_AUTO_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("AI_MAX_POSITION_PCT", "12.5")

    with TestClient(app) as client:
        response = client.get("/agent/status")

    body = response.json()
    assert body["model_connected"] is True
    assert body["execution_mode"] == "paper_auto"
    assert body["safety"]["max_position_pct"] == 12.5
from app.market_data.pykrx_provider import PykrxProvider


def test_get_candidates_empty_when_no_price_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.get("/agent/candidates")
        assert response.status_code == 200
        assert response.json() == []


def test_agent_chat_503_when_model_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"prompt": "포트폴리오 상태 알려줘"})
        assert response.status_code == 503


def test_agent_chat_returns_answer_without_executing_when_auto_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.delenv("AI_AUTO_EXECUTION_ENABLED", raising=False)
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)
    monkeypatch.setattr(
        "app.api.agent.ask_local_model",
        lambda system_prompt, user_prompt: (
            "지금은 관망을 추천합니다.\n"
            '```json\n{"decisions": [{"code": "005930", "action": "buy", "quantity": 1, "reason": "test"}]}\n```'
        ),
    )

    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"prompt": "지금 뭘 사야 해?", "scope": "대시보드"})
        assert response.status_code == 200
        body = response.json()
        assert "관망" in body["answer"]
        assert body["decisions"] == [{"code": "005930", "action": "buy", "quantity": 1, "reason": "test"}]
        assert body["order_ids"] == []

        runs = client.get("/agent/runs").json()
        assert runs[0]["reasoning"] == body["answer"]


def test_agent_chat_executes_and_blocks_by_position_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INITIAL_CAPITAL", "1000000")
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_AUTO_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("AI_MAX_POSITION_PCT", "20")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)
    monkeypatch.setattr(
        "app.api.agent.ask_local_model",
        lambda system_prompt, user_prompt: (
            '```json\n{"decisions": ['
            '{"code": "005930", "action": "buy", "quantity": 100, "reason": "ok"},'
            '{"code": "000660", "action": "buy", "quantity": 1000, "reason": "too big"}'
            ']}\n```'
        ),
    )

    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"prompt": "매수 후보 실행해줘"})
        assert response.status_code == 200
        body = response.json()
        assert len(body["order_ids"]) == 1
        assert len(body["blocked"]) == 1
        assert body["blocked"][0]["decision"]["code"] == "000660"
        assert "비중" in body["blocked"][0]["reason"]


def test_create_and_list_agent_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        response = client.post(
            "/agent/runs",
            json={
                "candidates": ["005930"],
                "decisions": [{"code": "005930", "action": "buy", "quantity": 1}],
                "reasoning": "strong momentum",
                "order_ids": [1],
            },
        )
        assert response.status_code == 200
        run_id = response.json()["id"]

        response = client.get("/agent/runs")
        assert response.status_code == 200
        runs = response.json()
        assert runs[0]["id"] == run_id
        assert runs[0]["candidates"] == ["005930"]
        assert runs[0]["decisions"] == [{"code": "005930", "action": "buy", "quantity": 1}]
        assert runs[0]["reasoning"] == "strong momentum"
        assert runs[0]["order_ids"] == [1]


def test_agent_chat_stream_yields_chunks_then_meta(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.delenv("AI_AUTO_EXECUTION_ENABLED", raising=False)
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)
    monkeypatch.setattr(
        "app.api.agent.stream_local_model",
        lambda system_prompt, user_prompt: iter(
            ["안녕", "하세요", '\n```json\n{"decisions": []}\n```']
        ),
    )

    with TestClient(app) as client:
        with client.stream("POST", "/agent/chat/stream", json={"prompt": "안녕"}) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

        assert body.startswith("안녕하세요")
        assert "<<<COPILOT_META>>>" in body
        meta = json.loads(body.split("<<<COPILOT_META>>>")[1])
        assert meta == {"order_ids": [], "blocked": []}
