import json

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .. import repository

router = APIRouter()


class JournalRequest(BaseModel):
    thesis: str = ""
    invalidation: str = ""
    target_price: float | None = None
    tags: list[str] = Field(default_factory=list)


def _decode(entry: dict | None, code: str | None = None) -> dict:
    if entry is None:
        return {"code": code, "thesis": "", "invalidation": "", "target_price": None, "tags": [], "updated_at": None}
    return {**entry, "tags": json.loads(entry["tags"])}


@router.get("/journal")
def list_journal(request: Request):
    return [_decode(entry) for entry in repository.get_journal_entries(request.app.state.conn)]


@router.get("/journal/{code}")
def get_journal(code: str, request: Request):
    return _decode(repository.get_journal_entry(request.app.state.conn, code), code)


@router.put("/journal/{code}")
def save_journal(code: str, req: JournalRequest, request: Request):
    entry = repository.upsert_journal_entry(
        request.app.state.conn,
        code,
        req.thesis.strip(),
        req.invalidation.strip(),
        req.target_price,
        json.dumps([tag.strip() for tag in req.tags if tag.strip()], ensure_ascii=False),
    )
    return _decode(entry)
