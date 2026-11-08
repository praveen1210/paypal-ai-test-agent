"""Minimal web UI + JSON API for the hosted demo (Render).

    uvicorn payagent.web:app --reload
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import Settings
from .report import to_markdown
from .runner import run_goal

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="AI Payment Test Agent", version="0.1.0")

EXAMPLE_GOALS = [
    "Test a partial refund on a captured order",
    "Verify I cannot refund more than the captured amount",
    "Authorize $40, capture $25, then void the rest and check the states",
    "Capturing the same order twice must fail",
    "Simulate a declined card at capture time and check the error is handled",
]


class RunRequest(BaseModel):
    goal: str = Field(min_length=5, max_length=500)
    fake: bool = False


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/examples")
def examples() -> list[str]:
    return EXAMPLE_GOALS


@app.post("/api/run")
async def run(req: RunRequest) -> dict:
    settings = Settings.from_env()
    if req.fake:
        settings = dataclasses.replace(settings, use_fake_paypal=True)
    try:
        result = await run_in_threadpool(run_goal, req.goal, settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = result.to_dict()
    data["markdown"] = to_markdown(result)
    return data
