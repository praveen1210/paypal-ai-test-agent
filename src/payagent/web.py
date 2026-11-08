"""Minimal web UI + JSON API for the hosted demo (Render).

    uvicorn payagent.web:app --reload
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .models import RunResult, Step
from .report import to_markdown
from .runner import run_goal

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="AI Payment Test Agent", version="0.1.0")
_RUNNING: set[asyncio.Task] = set()

EXAMPLE_GOALS = [
    "Test a partial refund on a captured order",
    "Verify I cannot refund more than the captured amount",
    "Authorize 40 USD, capture 25 as a partial capture, then void the rest and check the states",
    "Capturing the same order twice must fail",
    "Simulate a declined card at capture time and check the error is handled",
]


class RunRequest(BaseModel):
    goal: str = Field(min_length=5, max_length=500)
    fake: bool = False


def _settings(fake: bool) -> Settings:
    settings = Settings.from_env()
    if fake:
        settings = dataclasses.replace(settings, use_fake_paypal=True)
    try:
        settings.assert_paypal_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return settings


def _result_payload(result: RunResult) -> dict[str, Any]:
    data = result.to_dict()
    data["markdown"] = to_markdown(result)
    return data


def _step_summary(step: Step) -> dict[str, Any]:
    r = step.response
    return {
        "id": step.id, "tool": step.tool, "expect": step.expect, "error": step.error,
        "method": r.method if r else None, "path": r.path if r else None,
        "status": r.status if r else None, "debug_id": r.debug_id if r else None,
        "checks": [dataclasses.asdict(c) for c in step.checks],
    }


def _event_payload(kind: str, data: dict[str, Any]) -> dict[str, Any] | None:
    if kind == "step_finished":
        return _step_summary(data["step"])
    if kind == "check":
        return dataclasses.asdict(data["check"])
    if kind == "finished":
        return None  # the full result is sent as the final "result" event
    return data


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
    result = await run_in_threadpool(run_goal, req.goal, _settings(req.fake))
    return _result_payload(result)


@app.get("/api/run/stream")
async def run_stream(goal: str = Query(min_length=5, max_length=500), fake: bool = False) -> StreamingResponse:
    """Server-Sent Events: plan, step_started, step_finished, check, agent_note, approval_needed, result | error."""
    settings = _settings(fake)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

    def sink(kind: str, data: dict[str, Any]) -> None:  # called from the agent's worker thread
        payload = _event_payload(kind, data)
        if payload is not None:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    async def worker() -> None:
        try:
            result = await run_in_threadpool(run_goal, goal, settings, sink)
            await queue.put(("result", _result_payload(result)))
        except Exception as exc:  # surface to the browser instead of a silent hang
            await queue.put(("error", {"message": f"{type(exc).__name__}: {exc}"}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(worker())
    _RUNNING.add(task)  # keep a reference so the run finishes even if the browser disconnects
    task.add_done_callback(_RUNNING.discard)

    async def events():
        while (item := await queue.get()) is not None:
            kind, payload = item
            yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
