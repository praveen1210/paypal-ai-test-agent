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
