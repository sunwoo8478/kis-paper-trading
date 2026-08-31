import requests

from app.ai.context7 import Context7Context, fetch_context, get_context_for_prompt, parse_request


def _response(body: str, content_type: str = "application/json") -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = content_type
    response._content = body.encode()
    return response


def test_parse_request_only_accepts_explicit_docs_command():
    assert parse_request("포트폴리오 위험을 알려줘") is None
    assert parse_request("/docs next.js app router 캐시 사용법") == (
        "next.js",
        "app router 캐시 사용법",
    )
    assert parse_request("/context7 /fastapi/fastapi streaming response") == (
        "/fastapi/fastapi",
        "streaming response",
    )


def test_context7_searches_library_and_fetches_documentation(monkeypatch):
    monkeypatch.setenv("CONTEXT7_ENABLED", "true")
    monkeypatch.setenv("CONTEXT7_API_KEY", "test-key")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/libs/search"):
            return _response('{"results":[{"id":"/vercel/next.js","title":"Next.js"}]}')
        return _response("# App Router\nUse the current API.", "text/plain")

    monkeypatch.setattr("app.ai.context7.requests.get", fake_get)

    result = fetch_context("next.js", "test unique app router cache query")

    assert result == Context7Context(
        library_id="/vercel/next.js",
        library_title="Next.js",
        content="# App Router\nUse the current API.",
    )
    assert len(calls) == 2
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[1][1]["params"]["libraryId"] == "/vercel/next.js"


def test_context7_is_not_called_for_regular_trading_question(monkeypatch):
    monkeypatch.setenv("CONTEXT7_ENABLED", "true")
    monkeypatch.setenv("CONTEXT7_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.ai.context7.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected request")),
    )

    assert get_context_for_prompt("삼성전자 리스크를 분석해줘") is None
