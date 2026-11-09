import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

import payagent.web as web
from payagent.limits import DemoLimiter, LimitExceeded
from payagent.models import ApiResponse, Check, RunResult, Step
from payagent.report import to_junit


def _result(goal="g", agent_error=None):
    r = RunResult(goal=goal, started_at="2026-11-09T10:00:00+00:00", finished_at="2026-11-09T10:00:30+00:00",
                  model="m", agent_error=agent_error)
    r.steps.append(Step(id="S1", tool="refund_capture", args={}, expect="success",
                        response=ApiResponse("POST", "/r", 201, {})))
    r.checks += [Check("ok check", True, 1, 1, "S1"), Check("bad check", False, "5.00", "10.00", "S1")]
    return r


def test_junit_counts_failures_and_errors():
    root = ET.fromstring(to_junit([_result(), _result("g2", agent_error="boom")]))
    assert root.tag == "testsuites"
    assert (root.get("tests"), root.get("failures"), root.get("errors")) == ("5", "2", "1")
    suite = root.find("testsuite")
    assert suite.get("time") == "30.0"
    failure = suite.find("testcase/failure")
    assert failure is not None and 'expected "5.00", got "10.00"' in failure.get("message")
    assert suite.find("testcase").get("classname") == "payagent.refund_capture"


def test_limiter_caps_concurrency_and_per_client_runs():
    lim = DemoLimiter(max_concurrent=1, runs_per_window=2, window_seconds=600)
    lim.acquire("a")
    with pytest.raises(LimitExceeded, match="busy"):
        lim.acquire("b")
    lim.release()
    lim.acquire("a")
    lim.release()
    with pytest.raises(LimitExceeded, match="runs per"):
        lim.acquire("a")
    lim.acquire("b")  # other visitors are unaffected


def test_web_returns_429_when_busy(monkeypatch):
    monkeypatch.setattr(web, "limiter", DemoLimiter(max_concurrent=0, runs_per_window=5, window_seconds=600))
    resp = TestClient(web.app).get("/api/run/stream", params={"goal": "test a refund", "fake": "true"})
    assert resp.status_code == 429 and resp.headers["retry-after"] == "30"
