"""Tool definitions exposed to Claude, and the executor that runs them against PayPal."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from .models import Check, Finding, RunResult, Step
from .paypal_client import PayPalAuthError, PayPalClient
from .validator import _MISSING, OPERATORS, auto_checks, display, evaluate, get_path

EventSink = Callable[[str, dict[str, Any]], None]

_EXPECT = {
    "type": "string",
    "enum": ["success", "error"],
    "description": "What this step SHOULD do. Use 'error' for negative tests (e.g. over-refund). "
    "Built-in validation flips accordingly.",
}
_ISSUE = {
    "type": "string",
    "description": "For expect='error': the PayPal details[].issue code you expect, "
    "e.g. REFUND_AMOUNT_EXCEEDED, ORDER_ALREADY_CAPTURED, INSTRUMENT_DECLINED.",
}
_MOCK = {
    "type": "string",
    "description": "Sandbox negative testing: force PayPal to return this error code via the "
    "PayPal-Mock-Response header, e.g. INSTRUMENT_DECLINED, TRANSACTION_REFUSED, INTERNAL_SERVER_ERROR.",
}
_AMOUNT = {"type": "string", "description": "Decimal string, e.g. '25.00'."}
_CURRENCY = {"type": "string", "description": "ISO-4217 code, default USD."}


def _api_tool(name: str, description: str, props: dict[str, Any], required: list[str],
              mockable: bool = True) -> dict[str, Any]:
    properties = dict(props)
    properties["expect"] = _EXPECT
    properties["expected_issue"] = _ISSUE
    if mockable:
        properties["mock_error"] = _MOCK
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": properties, "required": required,
                         "additionalProperties": False},
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "record_plan",
        "description": "Call FIRST. Record the ordered test plan (one short line per step) before calling APIs.",
        "input_schema": {
            "type": "object",
            "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
    _api_tool(
        "create_order",
        "POST /v2/checkout/orders. payment_method='card' funds the order with a sandbox test card so it can be "
        "captured/authorized with no buyer interaction (use this by default). 'paypal' needs buyer approval "
        "in a browser (see wait_for_buyer_approval). Check the returned status: if it is already COMPLETED the "
        "card payment was processed at create time and captures/authorizations are in the response.",
        {
            "amount": _AMOUNT,
            "currency": _CURRENCY,
            "intent": {"type": "string", "enum": ["CAPTURE", "AUTHORIZE"]},
            "payment_method": {"type": "string", "enum": ["card", "paypal"]},
            "invoice_id": {"type": "string"},
        },
        ["amount"],
    ),
    _api_tool("get_order", "GET /v2/checkout/orders/{order_id}.", {"order_id": {"type": "string"}},
              ["order_id"], mockable=False),
    _api_tool("capture_order", "POST /v2/checkout/orders/{order_id}/capture (intent=CAPTURE orders).",
              {"order_id": {"type": "string"}}, ["order_id"]),
    _api_tool("authorize_order", "POST /v2/checkout/orders/{order_id}/authorize (intent=AUTHORIZE orders).",
              {"order_id": {"type": "string"}}, ["order_id"]),
    _api_tool("get_authorization", "GET /v2/payments/authorizations/{authorization_id}.",
              {"authorization_id": {"type": "string"}}, ["authorization_id"], mockable=False),
    _api_tool(
        "capture_authorization",
        "POST /v2/payments/authorizations/{authorization_id}/capture. Omit amount for full capture. "
        "No mock_error here: the sandbox answers mocks on this endpoint with a bare 403. To simulate a card "
        "decline, use mock_error on create_order (card orders are charged at create time).",
        {"authorization_id": {"type": "string"}, "amount": _AMOUNT, "currency": _CURRENCY,
         "final_capture": {"type": "boolean"}},
        ["authorization_id"],
        mockable=False,
    ),
    _api_tool("void_authorization", "POST /v2/payments/authorizations/{authorization_id}/void.",
              {"authorization_id": {"type": "string"}}, ["authorization_id"]),
    _api_tool("get_capture", "GET /v2/payments/captures/{capture_id}.", {"capture_id": {"type": "string"}},
              ["capture_id"], mockable=False),
    _api_tool(
        "refund_capture",
        "POST /v2/payments/captures/{capture_id}/refund. Omit amount for a full refund; give amount for partial.",
        {"capture_id": {"type": "string"}, "amount": _AMOUNT, "currency": _CURRENCY,
         "note": {"type": "string"}},
        ["capture_id"],
    ),
    _api_tool("get_refund", "GET /v2/payments/refunds/{refund_id}.", {"refund_id": {"type": "string"}},
              ["refund_id"], mockable=False),
    {
        "name": "wait_for_buyer_approval",
        "description": "Only for payment_method='paypal' orders: shows the approval link to the human operator "
        "and polls the order until it is APPROVED or the timeout passes.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"},
                           "timeout_seconds": {"type": "integer", "minimum": 10, "maximum": 300}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "assert_field",
        "description": "Add an explicit assertion on a previous step's JSON response, evaluated deterministically. "
        "Use for goal-specific checks the built-in rules don't cover (e.g. capture status becomes "
        "PARTIALLY_REFUNDED after a partial refund). path syntax: 'purchase_units[0].payments.captures[0].status'. "
        "Use path 'http_status' to assert the HTTP status code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "step_id": {"type": "string", "description": "e.g. 'S3'"},
                "path": {"type": "string"},
                "operator": {"type": "string", "enum": list(OPERATORS)},
                "expected": {"description": "Expected value (string/number/bool, or list for 'in')."},
                "description": {"type": "string", "description": "Plain-English name of the check."},
            },
            "required": ["step_id", "path", "operator", "description"],
            "additionalProperties": False,
        },
    },
    {
        "name": "retract_assertion",
        "description": "Withdraw one of YOUR OWN assert_field checks when the check itself was wrong (wrong path, "
        "wrong expectation), never to hide a product failure. Built-in checks cannot be retracted. The retraction "
        "and your reason are shown in the report.",
        "input_schema": {
            "type": "object",
            "properties": {
                "check_id": {"type": "string", "description": "The check_id returned by assert_field, e.g. 'C12'."},
                "reason": {"type": "string", "description": "Why the assertion was wrong."},
            },
            "required": ["check_id", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "finish",
        "description": "Call LAST, once testing is complete. Provide a plain-English summary and one finding per "
        "failed check or suspicious behaviour, explaining the likely bug and its business impact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "severity": {"type": "string", "enum": ["critical", "major", "minor", "info"]},
                            "explanation": {"type": "string"},
                            "step_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["title", "severity", "explanation"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["summary", "findings"],
            "additionalProperties": False,
        },
    },
]

API_TOOLS = {
    "create_order", "get_order", "capture_order", "authorize_order", "get_authorization",
    "capture_authorization", "void_authorization", "get_capture", "refund_capture", "get_refund",
}
_META_ARGS = {"expect", "expected_issue"}
MOCKABLE_TOOLS = {t["name"] for t in TOOL_DEFINITIONS if "mock_error" in t["input_schema"]["properties"]}
_MAX_BODY_CHARS = 6000


class ToolExecutor:
    def __init__(self, paypal: PayPalClient, result: RunResult, on_event: EventSink | None = None) -> None:
        self.paypal = paypal
        self.result = result
        self.on_event = on_event or (lambda _kind, _data: None)
        self.finished = False

    def execute(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Run one tool call. Returns (content for tool_result, is_error)."""
        try:
            if name in API_TOOLS:
                return self._api_call(name, args), False
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                return f"Unknown tool '{name}'.", True
            return handler(args), False
        except PayPalAuthError as exc:
            self.result.agent_error = str(exc)
            return f"PayPal authentication failed, stop testing: {exc}", True
        except (TypeError, ValueError, KeyError) as exc:
            return f"Invalid input for {name}: {exc}", True

    # --------------------------------------------------------------- API steps
    def _api_call(self, name: str, args: dict[str, Any]) -> str:
        if args.get("mock_error") and name not in MOCKABLE_TOOLS:
            raise ValueError(
                f"{name} does not accept mock_error (the sandbox returns a bare 403 for mocks there). "
                "To simulate a card decline, call create_order with mock_error; card orders are charged at create.")
        step = Step(id=f"S{len(self.result.steps) + 1}", tool=name, args=dict(args),
                    expect=args.get("expect", "success"))
        self.result.steps.append(step)
        self.on_event("step_started", {"step_id": step.id, "tool": name, "args": args})
        call_args = {k: v for k, v in args.items() if k not in _META_ARGS}
        try:
            step.response = getattr(self.paypal, name)(**call_args)
        except PayPalAuthError:
            raise
        except Exception as exc:  # network errors etc. are test results, not crashes
            step.error = f"{type(exc).__name__}: {exc}"
        step.checks = auto_checks(step)
        self.result.checks.extend(step.checks)
        self.on_event("step_finished", {"step": step})

        resp = step.response
        body_text = json.dumps(resp.body if resp else None)
        if len(body_text) > _MAX_BODY_CHARS:
            body_text = body_text[:_MAX_BODY_CHARS] + "...<truncated>"
        return json.dumps({
            "step_id": step.id,
            "request": f"{resp.method} {resp.path}" if resp else name,
            "http_status": resp.status if resp else None,
            "paypal_debug_id": resp.debug_id if resp else None,
            "transport_error": step.error,
            "built_in_checks": [{"check": c.description, "passed": c.passed, "actual": c.actual}
                                for c in step.checks],
            "response_body": body_text,
        })

    # -------------------------------------------------------------- meta tools
    def _tool_record_plan(self, args: dict[str, Any]) -> str:
        self.result.plan = [str(s) for s in args["steps"]]
        self.on_event("plan", {"steps": self.result.plan})
        return "Plan recorded. Execute it now."

    def _tool_assert_field(self, args: dict[str, Any]) -> str:
        step = next((s for s in self.result.steps if s.id == args["step_id"]), None)
        if step is None or step.response is None:
            raise ValueError(f"step_id {args['step_id']} not found or has no response")
        if args["path"] == "http_status":
            actual: Any = step.response.status
        else:
            actual = get_path(step.response.body, args["path"])
        if actual is _MISSING and args["operator"] not in {"exists", "not_exists"}:
            # A wrong path is a broken test, not a product failure: let the agent fix it.
            body = step.response.body
            keys = sorted(body) if isinstance(body, dict) else []
            raise ValueError(
                f"path '{args['path']}' is not in the {step.id} response, so nothing was recorded. "
                f"Top-level keys: {keys}. Fix the path, or use operator 'exists' if the field's absence is the bug."
            )
        passed = evaluate(args["operator"], actual, args.get("expected"))
        check = Check(description=args["description"], passed=passed, expected=args.get("expected"),
                      actual=display(actual), step_id=step.id, source="agent")
        step.checks.append(check)
        self.result.checks.append(check)
        self.on_event("check", {"check": check})
        reply: dict[str, Any] = {"check_id": f"C{len(self.result.checks)}", "passed": passed, "actual": check.actual}
        if not passed:
            body = step.response.body
            reply["hint"] = (f"Recorded as a FAILURE. {step.id} top-level keys: "
                             f"{sorted(body) if isinstance(body, dict) else []}. If your assertion (path or "
                             "expectation) was wrong rather than the API, call retract_assertion with this check_id.")
        return json.dumps(reply)

    def _tool_retract_assertion(self, args: dict[str, Any]) -> str:
        ref = str(args["check_id"]).strip().upper().removeprefix("C")
        if not ref.isdigit() or not 1 <= int(ref) <= len(self.result.checks):
            raise ValueError(f"unknown check_id {args['check_id']!r}")
        check = self.result.checks[int(ref) - 1]
        if check.source != "agent":
            raise ValueError("built-in checks cannot be retracted; only your own assert_field checks")
        reason = str(args["reason"]).strip()
        if not reason:
            raise ValueError("a reason is required")
        check.retracted = reason
        self.on_event("check_retracted", {"check": check})
        return json.dumps({"retracted": f"C{ref}", "reason": reason})

    def _tool_wait_for_buyer_approval(self, args: dict[str, Any]) -> str:
        order_id = args["order_id"]
        timeout = int(args.get("timeout_seconds", 180))
        first = self.paypal.get_order(order_id)
        link = next((lk.get("href") for lk in (first.body or {}).get("links", [])
                     if lk.get("rel") in {"payer-action", "approve"}), None)
        self.on_event("approval_needed", {"order_id": order_id, "url": link})
        deadline = time.time() + timeout
        status = (first.body or {}).get("status")
        while status != "APPROVED" and time.time() < deadline:
            time.sleep(5)
            status = (self.paypal.get_order(order_id).body or {}).get("status")
        return json.dumps({"order_id": order_id, "status": status, "approved": status == "APPROVED"})

    def _tool_finish(self, args: dict[str, Any]) -> str:
        self.result.summary = args["summary"]
        self.result.findings = [
            Finding(title=f["title"], severity=f.get("severity", "info"), explanation=f["explanation"],
                    step_ids=list(f.get("step_ids", [])))
            for f in args.get("findings", [])
        ]
        self.finished = True
        return "Report recorded."
