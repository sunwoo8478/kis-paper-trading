import os
import re
import threading
import time
from dataclasses import dataclass

import requests

_DEFAULT_BASE_URL = "https://context7.com/api"
_REQUEST_PATTERN = re.compile(r"^/(?:docs|context7)\s+(\S+)\s+(.+)$", re.IGNORECASE | re.DOTALL)
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE: dict[tuple[str, str], tuple[float, "Context7Context"]] = {}
_CACHE_LOCK = threading.Lock()


class Context7Error(Exception):
    pass


@dataclass(frozen=True)
class Context7Context:
    library_id: str
    library_title: str
    content: str


def is_configured() -> bool:
    enabled = os.getenv("CONTEXT7_ENABLED", "false").lower() in {"1", "true", "yes"}
    return enabled and bool(os.getenv("CONTEXT7_API_KEY", "").strip())


def parse_request(prompt: str) -> tuple[str, str] | None:
    """Parse an explicit `/docs <library> <question>` Context7 request."""
    match = _REQUEST_PATTERN.match(prompt.strip())
    if not match:
        return None
    return match.group(1), match.group(2).strip()


def get_context_for_prompt(prompt: str) -> Context7Context | None:
    request = parse_request(prompt)
    if request is None or not is_configured():
        return None
    return fetch_context(*request)


def fetch_context(library: str, query: str) -> Context7Context:
    cache_key = (library.lower(), query)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]

    api_key = os.getenv("CONTEXT7_API_KEY", "").strip()
    if not api_key:
        raise Context7Error("CONTEXT7_API_KEY not configured")

    base_url = os.getenv("CONTEXT7_API_URL", _DEFAULT_BASE_URL).rstrip("/")
    timeout = float(os.getenv("CONTEXT7_TIMEOUT_SECONDS", "15"))
    headers = {"Authorization": f"Bearer {api_key}"}

    if library.startswith("/"):
        library_id = library
        library_title = library.rsplit("/", 1)[-1]
    else:
        response = _get(
            f"{base_url}/v2/libs/search",
            headers=headers,
            params={"libraryName": library, "query": query, "fast": "true"},
            timeout=timeout,
        )
        _raise_for_status(response, "라이브러리 검색")
        results = response.json().get("results") or []
        if not results:
            raise Context7Error(f"Context7에서 '{library}' 라이브러리를 찾지 못했습니다")
        best = results[0]
        library_id = best["id"]
        library_title = best.get("title") or library_id

    response = _get(
        f"{base_url}/v2/context",
        headers=headers,
        params={"libraryId": library_id, "query": query, "type": "txt", "fast": "true"},
        timeout=timeout,
    )
    _raise_for_status(response, "문서 조회")
    content = response.text.strip()
    if not content:
        raise Context7Error("Context7가 빈 문서를 반환했습니다")

    max_chars = int(os.getenv("CONTEXT7_MAX_CONTEXT_CHARS", "12000"))
    result = Context7Context(library_id, library_title, content[:max_chars])
    with _CACHE_LOCK:
        _CACHE[cache_key] = (time.monotonic() + _CACHE_TTL_SECONDS, result)
    return result


def _get(url: str, **kwargs) -> requests.Response:
    try:
        return requests.get(url, **kwargs)
    except requests.RequestException as exc:
        raise Context7Error("Context7 서버에 연결할 수 없습니다") from exc


def _raise_for_status(response: requests.Response, operation: str) -> None:
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        detail = ""
        try:
            body = response.json()
            detail = body.get("message") or body.get("error") or ""
        except ValueError:
            pass
        suffix = f": {detail}" if detail else ""
        raise Context7Error(f"Context7 {operation} 실패 ({response.status_code}){suffix}") from exc
