import json

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import repository

router = APIRouter()


class AgentRunRequest(BaseModel):
    candidates: list[str]
    decisions: list[dict]
    reasoning: str
    order_ids: list[int]


@router.get("/agent/candidates")
def get_agent_candidates(request: Request):
    return repository.get_candidates(request.app.state.conn)


@router.post("/agent/runs")
def create_agent_run(req: AgentRunRequest, request: Request):
    run_id = repository.insert_agent_run(
        request.app.state.conn,
        candidates=json.dumps(req.candidates, ensure_ascii=False),
        decisions=json.dumps(req.decisions, ensure_ascii=False),
        reasoning=req.reasoning,
        order_ids=json.dumps(req.order_ids),
    )
    return {"id": run_id}


@router.get("/agent/runs")
def list_agent_runs(request: Request):
    runs = repository.get_agent_runs(request.app.state.conn)
    return [
        {
            "id": run["id"],
            "ts": run["ts"],
            "candidates": json.loads(run["candidates"]),
            "decisions": json.loads(run["decisions"]),
            "reasoning": run["reasoning"],
            "order_ids": json.loads(run["order_ids"]),
        }
        for run in runs
    ]
