"""Deterministic validation. The AI decides *what* to test; this module decides pass/fail.

Two sources of checks:
  * auto_checks(): built-in rules applied to every API step (status codes, money consistency,
    PayPal error-schema shape for negative tests).
  * evaluate(): generic assertions the agent requests via the `assert_field` tool.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import Check, Step

_MISSING = object()
_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")

OPERATORS = ("equals", "not_equals", "exists", "not_exists", "contains", "in", "gt", "gte", "lt", "lte")


def get_path(data: Any, path: str) -> Any:
    """Resolve 'purchase_units[0].payments.captures[0].status'. Returns _MISSING if absent."""
    if path in ("", "$"):
        return data
    current = data
    for name, index in _TOKEN.findall(path.removeprefix("$.")):
        if index:
            if not isinstance(current, list) or int(index) >= len(current):
                return _MISSING
            current = current[int(index)]
        else:
            if not isinstance(current, dict) or name not in current:
                return _MISSING
            current = current[name]
    return current


def _num(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _eq(a: Any, b: Any) -> bool:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na == nb  # "10.00" == "10" == 10
    return a == b


def evaluate(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "exists":
        return actual is not _MISSING
    if operator == "not_exists":
        return actual is _MISSING
    if actual is _MISSING:
        return False
    if operator == "equals":
        return _eq(actual, expected)
    if operator == "not_equals":
        return not _eq(actual, expected)
    if operator == "contains":
        if isinstance(actual, (list, tuple)):
            return any(_eq(item, expected) for item in actual)
        return str(expected) in str(actual)
    if operator == "in":
        return isinstance(expected, list) and any(_eq(actual, item) for item in expected)
    if operator in {"gt", "gte", "lt", "lte"}:
        na, nb = _num(actual), _num(expected)
        if na is None or nb is None:
            return False
        return {"gt": na > nb, "gte": na >= nb, "lt": na < nb, "lte": na <= nb}[operator]
    raise ValueError(f"Unknown operator '{operator}'. Use one of {OPERATORS}")


def display(value: Any) -> Any:
    return "<missing>" if value is _MISSING else value


def _check(step: Step, description: str, path: str, operator: str, expected: Any = None) -> Check:
    body = step.response.body if step.response else None
    actual = get_path(body, path)
    return Check(description=description, passed=evaluate(operator, actual, expected),
                 expected=expected if operator not in {"exists", "not_exists"} else operator,
                 actual=display(actual), step_id=step.id)


def _status_check(step: Step, description: str, ok: bool, expected: str) -> Check:
    return Check(description=description, passed=ok, expected=expected,
                 actual=step.response.status if step.response else None, step_id=step.id)


def auto_checks(step: Step) -> list[Check]:
    resp = step.response
    if resp is None:
        return [Check(f"{step.tool} executed", False, "API response", step.error, step.id)]
    args = step.args

    if step.expect == "error":
        checks = [
            _status_check(step, f"{step.tool} is rejected with a 4xx error", 400 <= resp.status < 500, "4xx"),
            _check(step, "Error body has PayPal 'name' field", "name", "exists"),
            _check(step, "Error body has 'debug_id' for support tracing", "debug_id", "exists"),
        ]
        if args.get("expected_issue"):
            issues = [d.get("issue") for d in (resp.body or {}).get("details", []) if isinstance(d, dict)]
            checks.append(Check(f"Error issue code is {args['expected_issue']}",
                                args["expected_issue"] in issues, args["expected_issue"], issues, step.id))
        return checks

    checks = [_status_check(step, f"{step.tool} returns HTTP 2xx", resp.ok, "2xx")]
    if not resp.ok:
        return checks  # later field checks would only repeat the same failure

    tool = step.tool
    if tool == "create_order":
        checks += [
            _check(step, "Order id is returned", "id", "exists"),
            _check(step, "Order status is valid after create", "status", "in",
                   ["CREATED", "APPROVED", "PAYER_ACTION_REQUIRED", "COMPLETED"]),
            _check(step, "Order amount matches request", "purchase_units[0].amount.value", "equals",
                   args.get("amount")),
            _check(step, "Order currency matches request", "purchase_units[0].amount.currency_code", "equals",
                   args.get("currency", "USD")),
        ]
    elif tool == "capture_order":
        checks += [
            _check(step, "Order status is COMPLETED after capture", "status", "equals", "COMPLETED"),
            _check(step, "Capture status is COMPLETED", "purchase_units[0].payments.captures[0].status",
                   "equals", "COMPLETED"),
        ]
        order_amt = get_path(resp.body, "purchase_units[0].amount.value")
        if order_amt is not _MISSING:
            checks.append(_check(step, "Captured amount equals order amount",
                                 "purchase_units[0].payments.captures[0].amount.value", "equals", order_amt))
    elif tool == "authorize_order":
        checks.append(_check(step, "Authorization status is CREATED",
                             "purchase_units[0].payments.authorizations[0].status", "equals", "CREATED"))
    elif tool == "capture_authorization":
        checks.append(_check(step, "Capture status is COMPLETED", "status", "equals", "COMPLETED"))
        if args.get("amount"):
            checks.append(_check(step, "Captured amount matches request", "amount.value", "equals", args["amount"]))
    elif tool == "refund_capture":
        checks.append(_check(step, "Refund status is COMPLETED or PENDING", "status", "in",
                             ["COMPLETED", "PENDING"]))
        if args.get("amount"):
            checks.append(_check(step, "Refunded amount matches request", "amount.value", "equals", args["amount"]))
    elif tool == "void_authorization" and resp.body:
        checks.append(_check(step, "Authorization status is VOIDED", "status", "equals", "VOIDED"))
    elif tool.startswith("get_"):
        id_arg = next((v for k, v in args.items() if k.endswith("_id")), None)
        if id_arg:
            checks.append(_check(step, "Fetched resource id matches", "id", "equals", id_arg))
    return checks
