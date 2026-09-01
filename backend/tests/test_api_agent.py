import json
import sqlite3

from fastapi.testclient import TestClient

from app import repository
from app.ai.context7 import Context7Context
from app.main import app
from app.market_data.base import OhlcvBar, Stock
from app.market_data.pykrx_provider import PykrxProvider


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


def test_autonomous_control_endpoints_persist_start_and_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AI_AUTONOMOUS_ENABLED", "false")

    with TestClient(app) as client:
        initial = client.get("/agent/autonomous/status")
        started = client.post("/agent/autonomous/start")
        stopped = client.post("/agent/autonomous/stop")

    assert initial.status_code == 200
    assert initial.json()["enabled"] is False
    assert started.json()["enabled"] is True
    assert stopped.json()["enabled"] is False


def test_start_experiment_requires_confirmation_and_resets_without_deleting_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "experiment.db"))
    monkeypatch.setenv("AI_AUTONOMOUS_ENABLED", "false")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)
    monkeypatch.setattr("app.api.agent._benchmark_quote", lambda: ("KOSPI", 3000.0))

    with TestClient(app) as client:
        repository.apply_buy(app.state.conn, "005930", 10, 1000.0)
        repository.record_order(app.state.conn, "005930", "buy", 10, 1000.0)
        rejected = client.post("/agent/experiment/start", json={"confirm_reset": False})
        started = client.post(
            "/agent/experiment/start",
            json={"name": "AI 전용", "initial_capital": 10_000_000, "confirm_reset": True},
        )
        status = client.get("/agent/experiment")

    assert rejected.status_code == 400
    assert started.status_code == 200
    assert started.json()["experiment"]["name"] == "AI 전용"
    assert status.json()["active"] is True
    assert status.json()["experiment"]["return_pct"] == 0
    assert status.json()["experiment"]["order_count"] == 0
    assert status.json()["experiment"]["benchmark_symbol"] == "KOSPI"
    assert status.json()["experiment"]["benchmark_return_pct"] == 0


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


def test_agent_chat_answers_portfolio_facts_without_model_guessing(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "facts.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)
    monkeypatch.setattr(
        "app.api.agent.ask_local_model",
        lambda *args: (_ for _ in ()).throw(AssertionError("facts must bypass model")),
    )

    with TestClient(app) as client:
        repository.upsert_stocks(app.state.conn, [Stock("005930", "삼성전자", "KOSPI")])
        repository.apply_buy(app.state.conn, "005930", 10, 900.0)
        response = client.post("/agent/chat", json={"prompt": "현재 계좌 상황을 요약해줘"})

    assert response.status_code == 200
    assert "삼성전자(005930)" in response.json()["answer"]
    assert "보유 종목은 1개" in response.json()["answer"]
    assert response.json()["decisions"] == []


def test_agent_chat_answers_recent_orders_from_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "orders-facts.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        order_id = repository.record_order(app.state.conn, "005930", "buy", 3, 1000.0)
        response = client.post("/agent/chat", json={"prompt": "최근 주문 상태를 검토해줘"})

    assert response.status_code == 200
    assert f"#{order_id}" in response.json()["answer"]
    assert "BUY 3주" in response.json()["answer"]


def test_agent_chat_answers_buy_reason_from_recorded_autonomous_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "reason-facts.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)

    with TestClient(app) as client:
        repository.upsert_stocks(app.state.conn, [Stock("005930", "삼성전자", "KOSPI")])
        repository.insert_agent_run(
            app.state.conn,
            candidates='["005930"]',
            decisions='[{"code":"005930","action":"buy","reason":"거래량과 추세 확인"}]',
            reasoning="test",
            order_ids="[1]",
        )
        response = client.post("/agent/chat", json={"prompt": "삼성전자 왜 샀어?"})

    assert response.status_code == 200
    assert "거래량과 추세 확인" in response.json()["answer"]


def test_agent_chat_injects_context7_docs_into_local_model_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)
    monkeypatch.setattr(
        "app.api.agent.get_context_for_prompt",
        lambda prompt: Context7Context("/vercel/next.js", "Next.js", "CURRENT DOCUMENTATION"),
    )
    captured = {}

    def fake_model(system_prompt, user_prompt):
        captured["prompt"] = user_prompt
        return '문서를 확인했습니다.\n```json\n{"decisions": []}\n```'

    monkeypatch.setattr("app.api.agent.ask_local_model", fake_model)

    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"prompt": "/docs next.js app router"})

    assert response.status_code == 200
    assert "CURRENT DOCUMENTATION" in captured["prompt"]
    assert "<context7_docs>" in captured["prompt"]


def test_agent_chat_returns_server_quote_without_model_guessing(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 251750.0)
    monkeypatch.setattr(
        "app.api.agent.ask_local_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("model must not guess a live quote")),
    )

    with TestClient(app) as client:
        repository.upsert_stocks(app.state.conn, [Stock("005930", "삼성전자", "KOSPI")])
        response = client.post("/agent/chat", json={"prompt": "삼성 전자 현재 1주 가격 알려줘"})

    assert response.status_code == 200
    body = response.json()
    assert "251,750원" in body["answer"]
    assert "삼성전자(005930)" in body["answer"]
    assert body["decisions"] == []


def test_agent_chat_stream_returns_server_quote_without_json_fence(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 251750.0)
    monkeypatch.setattr(
        "app.api.agent.stream_local_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("model must not guess a live quote")),
    )

    with TestClient(app) as client:
        repository.upsert_stocks(app.state.conn, [Stock("005930", "삼성전자", "KOSPI")])
        with client.stream(
            "POST", "/agent/chat/stream", json={"prompt": "삼성전자 현재 주가 정보 알려줘"}
        ) as response:
            body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "251,750원" in body
    assert "```json" not in body
    assert "<<<COPILOT_META>>>" in body


def test_agent_chat_stream_hides_model_decision_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)
    monkeypatch.setattr(
        "app.api.agent.stream_local_model",
        lambda system_prompt, user_prompt: iter(
            ["분석 결과", "입니다.\n``", "`json\n", '{"decisions": []}', "\n```"]
        ),
    )

    with TestClient(app) as client:
        with client.stream("POST", "/agent/chat/stream", json={"prompt": "시장 분석"}) as response:
            body = "".join(response.iter_text())

    assert "분석 결과입니다." in body
    assert "```json" not in body
    assert '"decisions"' not in body.split("<<<COPILOT_META>>>")[0]


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


def test_autonomous_backtest_compare_returns_multi_period_verdicts(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DB_PATH", db_path)
    conn = sqlite3.connect(db_path)
    repository.init_db(conn, 1_000_000)
    repository.upsert_stocks(conn, [Stock("005930", "삼성전자", "KOSPI")])
    bars = [
        OhlcvBar(
            date=f"2026-06-{index + 1:02d}", open=900 + index, high=910 + index,
            low=890 + index, close=900 + index * 2, volume=1000 + index,
        )
        for index in range(30)
    ]
    repository.upsert_price_history(conn, "005930", bars)
    conn.close()

    with TestClient(app) as client:
        response = client.get("/agent/autonomous/backtest/compare?universe=10")

    assert response.status_code == 200
    body = response.json()
    assert [period["period_days"] for period in body["periods"]] == [60, 120, 252]
    assert body["overall_verdict"] in {"pass", "warn", "fail"}


def test_agent_chat_explains_blocked_buy_from_latest_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "blocked-facts.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)
    monkeypatch.setattr(
        "app.api.agent.ask_local_model",
        lambda *args: (_ for _ in ()).throw(AssertionError("facts must bypass model")),
    )

    with TestClient(app) as client:
        repository.insert_autonomous_cycle(
            app.state.conn,
            started_at="2026-09-01T00:00:00+00:00",
            status="observed",
            market_open=True,
            decisions="[]",
            order_ids="[]",
            total_value=1_000_000,
            error=None,
            market_regime="bearish",
            target_exposure_pct=20.0,
            blocked_decisions=json.dumps([
                {"code": "005930", "action": "buy", "rule": "bearish_regime", "reason": "하락장으로 분류되어 신규 매수 중단"}
            ], ensure_ascii=False),
        )
        response = client.post("/agent/chat", json={"prompt": "오늘 왜 아무것도 안 샀어?", "scope": "dashboard"})

    assert response.status_code == 200
    body = response.json()
    assert "bearish_regime" not in body["answer"]
    assert "하락장" in body["answer"]
    assert "20" in body["answer"]


def test_agent_chat_explains_market_regime_and_target_exposure(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "regime-facts.db"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(PykrxProvider, "get_latest_price", lambda self, code: 1000.0)
    monkeypatch.setattr(
        "app.api.agent.ask_local_model",
        lambda *args: (_ for _ in ()).throw(AssertionError("facts must bypass model")),
    )

    with TestClient(app) as client:
        repository.insert_autonomous_cycle(
            app.state.conn,
            started_at="2026-09-01T00:00:00+00:00",
            status="observed",
            market_open=True,
            decisions="[]",
            order_ids="[]",
            total_value=1_000_000,
            error=None,
            market_regime="neutral",
            target_exposure_pct=80.0,
            blocked_decisions="[]",
        )
        response = client.post("/agent/chat", json={"prompt": "현재 장세와 목표 투자비중 알려줘", "scope": "dashboard"})

    assert response.status_code == 200
    body = response.json()
    assert "neutral" in body["answer"]
    assert "80" in body["answer"]
