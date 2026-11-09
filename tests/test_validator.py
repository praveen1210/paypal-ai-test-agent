from payagent.models import ApiResponse, Step
from payagent.validator import _MISSING, auto_checks, evaluate, get_path

BODY = {"id": "O1", "purchase_units": [{"amount": {"value": "10.00"}, "payments": {"captures": [{"status": "COMPLETED"}]}}]}


def test_get_path_resolves_nested_lists():
    assert get_path(BODY, "purchase_units[0].payments.captures[0].status") == "COMPLETED"
    assert get_path(BODY, "purchase_units[3].amount") is _MISSING
    assert get_path(BODY, "nope.deeper") is _MISSING


def test_evaluate_compares_money_numerically():
    assert evaluate("equals", "10.00", "10")
    assert evaluate("lt", "4.99", 5)
    assert evaluate("in", "PENDING", ["COMPLETED", "PENDING"])
    assert not evaluate("equals", _MISSING, None)
    assert evaluate("not_exists", _MISSING, None)


def _step(tool, status, body, expect="success", **args):
    return Step(id="S1", tool=tool, args=args, expect=expect,
                response=ApiResponse("POST", "/x", status, body))


def test_refund_amount_mismatch_fails():
    step = _step("refund_capture", 201, {"status": "COMPLETED", "amount": {"value": "9.00"}}, amount="5.00")
    results = {c.description: c.passed for c in auto_checks(step)}
    assert results["refund_capture returns HTTP 2xx"]
    assert not results["Refunded amount matches request"]


def test_negative_test_passes_on_expected_error():
    body = {"name": "UNPROCESSABLE_ENTITY", "debug_id": "abc", "details": [{"issue": "REFUND_AMOUNT_EXCEEDED"}]}
    step = _step("refund_capture", 422, body, expect="error", expected_issue="REFUND_AMOUNT_EXCEEDED")
    assert all(c.passed for c in auto_checks(step))


def test_negative_test_fails_when_api_accepts():
    step = _step("refund_capture", 201, {"status": "COMPLETED"}, expect="error")
    assert not all(c.passed for c in auto_checks(step))


def test_assert_on_missing_path_is_a_test_error_not_a_failure():
    from payagent.models import RunResult
    from payagent.tools import ToolExecutor

    result = RunResult(goal="g", started_at="t")
    result.steps.append(Step(id="S1", tool="get_refund", args={}, expect="success",
                             response=ApiResponse("GET", "/r", 200, {"id": "R1", "status": "COMPLETED"})))
    ex = ToolExecutor(paypal=None, result=result)
    content, is_error = ex.execute("assert_field", {"step_id": "S1", "path": "capture_id", "operator": "equals",
                                                    "expected": "C1", "description": "linked"})
    assert is_error and "Top-level keys" in content and result.checks == []
    _, is_error = ex.execute("assert_field", {"step_id": "S1", "path": "capture_id", "operator": "exists",
                                              "description": "capture_id present"})
    assert not is_error and result.checks[-1].passed is False


def test_agent_can_retract_own_assertion_but_not_builtin_checks():
    import json as _json

    from payagent.models import Check, RunResult
    from payagent.report import to_junit, to_markdown
    from payagent.tools import ToolExecutor

    result = RunResult(goal="g", started_at="t")
    result.steps.append(Step(id="S1", tool="get_refund", args={}, expect="success",
                             response=ApiResponse("GET", "/r", 200, {"id": "R1", "status": "COMPLETED"})))
    result.checks.append(Check("built-in", True, step_id="S1"))
    ex = ToolExecutor(paypal=None, result=result)
    reply = _json.loads(ex.execute("assert_field", {"step_id": "S1", "path": "refund.status", "operator": "exists",
                                                     "description": "wrong path"})[0])
    assert reply["check_id"] == "C2" and reply["passed"] is False and "retract_assertion" in reply["hint"]
    assert result.verdict == "FAIL"

    _, is_error = ex.execute("retract_assertion", {"check_id": "C1", "reason": "x"})
    assert is_error  # built-in checks are protected
    content, is_error = ex.execute("retract_assertion", {"check_id": "C2", "reason": "status is top-level"})
    assert not is_error and result.checks[1].retracted == "status is top-level"
    assert result.verdict == "PASS"
    assert "1 retracted" in to_markdown(result) and "retracted by agent" in to_junit(result)


def test_mock_error_rejected_where_sandbox_does_not_support_it():
    from payagent.models import RunResult
    from payagent.tools import MOCKABLE_TOOLS, ToolExecutor

    assert "create_order" in MOCKABLE_TOOLS and "capture_authorization" not in MOCKABLE_TOOLS
    result = RunResult(goal="g", started_at="t")
    content, is_error = ToolExecutor(paypal=None, result=result).execute(
        "capture_authorization", {"authorization_id": "A1", "mock_error": "INSTRUMENT_DECLINED"})
    assert is_error and "create_order" in content and result.steps == []
