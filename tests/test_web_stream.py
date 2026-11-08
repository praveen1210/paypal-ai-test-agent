"""The SSE endpoint streams plan/step events and ends with the full result."""

import json

from fastapi.testclient import TestClient
from test_agent_offline import ScriptedClaude

import payagent.agent
from payagent.web import app


def test_stream_emits_live_events_then_result(monkeypatch):
    monkeypatch.setattr(payagent.agent.anthropic, "Anthropic", ScriptedClaude)
    client = TestClient(app)
    events = []
    with client.stream("GET", "/api/run/stream", params={"goal": "test a partial refund", "fake": "true"}) as resp:
        assert resp.status_code == 200
        kind = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                events.append((kind, json.loads(line[6:])))

    kinds = [k for k, _ in events]
    assert kinds[0] == "plan"
    assert kinds.count("step_started") == kinds.count("step_finished") == 5
    assert kinds[-1] == "result"
    result = events[-1][1]
    assert result["verdict"] == "PASS" and "markdown" in result
    finished = next(d for k, d in events if k == "step_finished")
    assert finished["status"] == 201 and finished["checks"]


def test_stream_rejects_short_goal():
    assert TestClient(app).get("/api/run/stream", params={"goal": "x"}).status_code == 422
