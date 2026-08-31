import json
import os
import re

import requests

_DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class LocalModelError(Exception):
    pass


def is_configured() -> bool:
    return bool(os.getenv("AI_PROVIDER", "").strip() and os.getenv("AI_MODEL", "").strip())


def ask_local_model(system_prompt: str, user_prompt: str) -> str:
    model = os.getenv("AI_MODEL", "").strip()
    if not model:
        raise LocalModelError("AI_MODEL not configured")
    base_url = os.getenv("AI_OLLAMA_URL", _DEFAULT_BASE_URL).rstrip("/")

    response = requests.post(
        f"{base_url}/api/generate",
        json={
            "model": model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 8192},
        },
        timeout=90,
    )
    response.raise_for_status()
    text = response.json().get("response")
    if not text:
        raise LocalModelError("empty response from local model")
    return text


def stream_local_model(system_prompt: str, user_prompt: str):
    model = os.getenv("AI_MODEL", "").strip()
    if not model:
        raise LocalModelError("AI_MODEL not configured")
    base_url = os.getenv("AI_OLLAMA_URL", _DEFAULT_BASE_URL).rstrip("/")

    response = requests.post(
        f"{base_url}/api/generate",
        json={
            "model": model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": True,
            "options": {"temperature": 0.1, "num_ctx": 8192},
        },
        timeout=120,
        stream=True,
    )
    response.raise_for_status()
    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        chunk = json.loads(line)
        if chunk.get("response"):
            yield chunk["response"]
        if chunk.get("done"):
            break


def extract_json_block(text: str) -> dict | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
