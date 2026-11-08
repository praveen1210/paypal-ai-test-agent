"""In-memory stand-in for the PayPal sandbox.

Used by the test suite and by `--fake` runs so the agent can be demoed without sandbox keys.
It models the happy paths plus the common business-rule errors (over-refund, double capture,
mock error codes). It is NOT a full PayPal emulator; the real sandbox is the source of truth.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any

from .paypal_client import PayPalClient


def _id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:15].upper()


def _money(currency: str, value: Decimal) -> dict[str, str]:
    return {"currency_code": currency, "value": f"{value:.2f}"}


def _error(status: int, name: str, issue: str, description: str) -> tuple[int, dict[str, Any]]:
    return status, {
        "name": name,
        "message": "The requested action could not be performed.",
        "debug_id": uuid.uuid4().hex[:13],
        "details": [{"issue": issue, "description": description}],
    }


class FakePayPalClient(PayPalClient):
    def __init__(self) -> None:
        super().__init__("fake-id", "fake-secret", base_url="https://fake.paypal.local")
        self.orders: dict[str, dict[str, Any]] = {}
        self.authorizations: dict[str, dict[str, Any]] = {}
        self.captures: dict[str, dict[str, Any]] = {}
        self.refunds: dict[str, dict[str, Any]] = {}

    def get_access_token(self) -> str:
        return "fake-token"

    def _send(self, method, path, body, headers):  # noqa: ANN001 - matches parent signature
        mock = headers.get("PayPal-Mock-Response")
        if mock:
            code = re.search(r'"mock_application_codes":\s*"([A-Z_]+)"', mock)
            status, payload = _error(422, "UNPROCESSABLE_ENTITY", code.group(1) if code else "MOCK",
                                     "Mocked error response.")
            return status, payload, payload["debug_id"]
        status, payload = self._route(method, path, body or {})
        return status, payload, uuid.uuid4().hex[:13]

    # ------------------------------------------------------------------ routing
    def _route(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        parts = path.strip("/").split("/")
        if parts[:3] == ["v2", "checkout", "orders"]:
            if len(parts) == 3 and method == "POST":
                return self._create_order(body)
            order = self.orders.get(parts[3]) if len(parts) > 3 else None
            if order is None:
                return _error(404, "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID", "Order not found.")
            if len(parts) == 4 and method == "GET":
                return 200, order
            if len(parts) == 5 and parts[4] == "capture":
                return self._capture_order(order)
            if len(parts) == 5 and parts[4] == "authorize":
                return self._authorize_order(order)
        if parts[:2] == ["v2", "payments"] and len(parts) >= 4:
            kind, rid = parts[2], parts[3]
            store = {"authorizations": self.authorizations, "captures": self.captures,
                     "refunds": self.refunds}.get(kind, {})
            obj = store.get(rid)
            if obj is None:
                return _error(404, "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID", f"{kind[:-1]} not found.")
            if len(parts) == 4 and method == "GET":
                return 200, obj
            action = parts[4] if len(parts) > 4 else ""
            if kind == "captures" and action == "refund":
                return self._refund(obj, body)
            if kind == "authorizations" and action == "capture":
                return self._capture_auth(obj, body)
            if kind == "authorizations" and action == "void":
                if obj["status"] != "CREATED":
                    return _error(422, "UNPROCESSABLE_ENTITY", "PREVIOUSLY_VOIDED"
                                  if obj["status"] == "VOIDED" else "CANNOT_BE_VOIDED", "Cannot void.")
                obj["status"] = "VOIDED"
                return 200, obj
        return _error(404, "NOT_FOUND", "UNSUPPORTED_ROUTE", f"{method} {path} not supported by fake.")

    # --------------------------------------------------------------- handlers
    def _create_order(self, body: dict[str, Any]) -> tuple[int, Any]:
        try:
            unit = body["purchase_units"][0]
            amount = Decimal(unit["amount"]["value"])
            currency = unit["amount"]["currency_code"]
        except (KeyError, IndexError, ArithmeticError):
            return _error(400, "INVALID_REQUEST", "MISSING_REQUIRED_PARAMETER", "purchase_units invalid.")
        if amount <= 0:
            return _error(422, "UNPROCESSABLE_ENTITY", "CANNOT_BE_ZERO_OR_NEGATIVE", "Amount must be > 0.")
        source = body.get("payment_source", {})
        order = {
            "id": _id("ORD"),
            "intent": body.get("intent", "CAPTURE"),
            "status": "APPROVED" if "card" in source else "PAYER_ACTION_REQUIRED",
            "purchase_units": [{"reference_id": "default", "amount": _money(currency, amount), "payments": {}}],
            "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=FAKE"}],
        }
        self.orders[order["id"]] = order
        return 201, order

    def _capture_order(self, order: dict[str, Any]) -> tuple[int, Any]:
        if order["status"] == "COMPLETED":
            return _error(422, "UNPROCESSABLE_ENTITY", "ORDER_ALREADY_CAPTURED", "Order already captured.")
        if order["status"] != "APPROVED":
            return _error(422, "UNPROCESSABLE_ENTITY", "ORDER_NOT_APPROVED", "Payer has not approved.")
        if order["intent"] != "CAPTURE":
            return _error(422, "UNPROCESSABLE_ENTITY", "ACTION_DOES_NOT_MATCH_INTENT", "Intent is AUTHORIZE.")
        unit = order["purchase_units"][0]
        cap = self._new_capture(unit["amount"]["currency_code"], Decimal(unit["amount"]["value"]), order["id"])
        unit["payments"]["captures"] = [cap]
        order["status"] = "COMPLETED"
        return 201, order

    def _authorize_order(self, order: dict[str, Any]) -> tuple[int, Any]:
        if order["intent"] != "AUTHORIZE":
            return _error(422, "UNPROCESSABLE_ENTITY", "ACTION_DOES_NOT_MATCH_INTENT", "Intent is CAPTURE.")
        if order["status"] != "APPROVED":
            return _error(422, "UNPROCESSABLE_ENTITY", "ORDER_ALREADY_AUTHORIZED"
                          if order["status"] == "COMPLETED" else "ORDER_NOT_APPROVED", "Cannot authorize.")
        unit = order["purchase_units"][0]
        auth = {"id": _id("AUT"), "status": "CREATED", "amount": dict(unit["amount"]),
                "captured": "0.00", "order_id": order["id"]}
        self.authorizations[auth["id"]] = auth
        unit["payments"]["authorizations"] = [{k: v for k, v in auth.items() if k != "captured"}]
        order["status"] = "COMPLETED"
        return 201, order

    def _capture_auth(self, auth: dict[str, Any], body: dict[str, Any]) -> tuple[int, Any]:
        if auth["status"] in {"VOIDED", "CAPTURED"}:
            return _error(422, "UNPROCESSABLE_ENTITY", "AUTHORIZATION_" + auth["status"], "Not capturable.")
        currency = auth["amount"]["currency_code"]
        total = Decimal(auth["amount"]["value"])
        remaining = total - Decimal(auth["captured"])
        value = Decimal(body.get("amount", {}).get("value", remaining))
        if value > remaining:
            return _error(422, "UNPROCESSABLE_ENTITY", "MAX_CAPTURE_AMOUNT_EXCEEDED", "Exceeds authorization.")
        auth["captured"] = f"{Decimal(auth['captured']) + value:.2f}"
        final = body.get("final_capture", True) or Decimal(auth["captured"]) == total
        auth["status"] = "CAPTURED" if final else "PARTIALLY_CAPTURED"
        return 201, self._new_capture(currency, value, auth["order_id"], final)

    def _new_capture(self, currency: str, value: Decimal, order_id: str, final: bool = True) -> dict[str, Any]:
        cap = {"id": _id("CAP"), "status": "COMPLETED", "amount": _money(currency, value),
               "final_capture": final, "refunded": "0.00",
               "supplementary_data": {"related_ids": {"order_id": order_id}}}
        self.captures[cap["id"]] = cap
        return {k: v for k, v in cap.items() if k != "refunded"}

    def _refund(self, cap: dict[str, Any], body: dict[str, Any]) -> tuple[int, Any]:
        currency = cap["amount"]["currency_code"]
        remaining = Decimal(cap["amount"]["value"]) - Decimal(cap["refunded"])
        if remaining <= 0:
            return _error(422, "UNPROCESSABLE_ENTITY", "CAPTURE_FULLY_REFUNDED", "Already fully refunded.")
        req = body.get("amount")
        if req and req.get("currency_code") != currency:
            return _error(422, "UNPROCESSABLE_ENTITY", "REFUND_CAPTURE_CURRENCY_MISMATCH", "Currency mismatch.")
        value = Decimal(req["value"]) if req else remaining
        if value <= 0:
            return _error(422, "UNPROCESSABLE_ENTITY", "REFUND_AMOUNT_INVALID", "Must be > 0.")
        if value > remaining:
            return _error(422, "UNPROCESSABLE_ENTITY", "REFUND_AMOUNT_EXCEEDED", "Exceeds refundable amount.")
        cap["refunded"] = f"{Decimal(cap['refunded']) + value:.2f}"
        cap["status"] = "REFUNDED" if Decimal(cap["refunded"]) == Decimal(cap["amount"]["value"]) \
            else "PARTIALLY_REFUNDED"
        refund = {"id": _id("REF"), "status": "COMPLETED", "amount": _money(currency, value),
                  "capture_id": cap["id"]}
        self.refunds[refund["id"]] = refund
        return 201, refund
