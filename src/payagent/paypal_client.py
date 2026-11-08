"""Thin PayPal REST client: OAuth2, Orders v2, Payments v2 (captures, authorizations, refunds).

Every call returns an ApiResponse instead of raising on 4xx/5xx, because a test agent needs to
*observe* error responses (negative tests), not crash on them.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx

from .models import ApiResponse


class PayPalAuthError(RuntimeError):
    pass


def _mask_card(body: Any) -> Any:
    """Return a copy of a request body that is safe to put in reports."""
    if not isinstance(body, dict):
        return body
    clone = json.loads(json.dumps(body))
    card = clone.get("payment_source", {}).get("card")
    if isinstance(card, dict) and "number" in card:
        card["number"] = "************" + str(card["number"])[-4:]
        card.pop("security_code", None)
    return clone


class PayPalClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = "https://api-m.sandbox.paypal.com",
        test_card_number: str = "4111111111111111",
        test_card_expiry: str = "2030-12",
        http: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.test_card_number = test_card_number
        self.test_card_expiry = test_card_expiry
        self._http = http or httpx.Client(timeout=timeout)
        self._token: str | None = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------ auth
    def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = self._http.post(
            f"{self.base_url}/v1/oauth2/token",
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise PayPalAuthError(f"OAuth token request failed: HTTP {resp.status_code} {resp.text[:300]}")
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 300))
        return self._token

    # --------------------------------------------------------------- transport
    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        mock_error: str | None = None,
    ) -> ApiResponse:
        headers = {
            "Content-Type": "application/json",
            "Prefer": "return=representation",
            "PayPal-Request-Id": str(uuid.uuid4()),
        }
        if mock_error:
            # PayPal sandbox negative testing: forces the API to return the given error code.
            headers["PayPal-Mock-Response"] = json.dumps({"mock_application_codes": mock_error})
        started = time.perf_counter()
        status, payload, debug_id = self._send(method, path, body, headers)
        return ApiResponse(
            method=method,
            path=path,
            status=status,
            body=payload,
            debug_id=debug_id,
            request_body=_mask_card(body),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def _send(
        self, method: str, path: str, body: dict[str, Any] | None, headers: dict[str, str]
    ) -> tuple[int, Any, str | None]:
        headers = {**headers, "Authorization": f"Bearer {self.get_access_token()}"}
        resp = self._http.request(method, f"{self.base_url}{path}", json=body, headers=headers)
        try:
            payload: Any = resp.json() if resp.content else {}
        except ValueError:
            payload = {"raw": resp.text[:2000]}
        return resp.status_code, payload, resp.headers.get("paypal-debug-id")

    # ------------------------------------------------------------- Orders v2
    def create_order(
        self,
        amount: str,
        currency: str = "USD",
        intent: str = "CAPTURE",
        payment_method: str = "card",
        invoice_id: str | None = None,
        mock_error: str | None = None,
    ) -> ApiResponse:
        unit: dict[str, Any] = {
            "reference_id": "default",
            "amount": {"currency_code": currency, "value": amount},
        }
        if invoice_id:
            unit["invoice_id"] = invoice_id
        body: dict[str, Any] = {"intent": intent, "purchase_units": [unit]}
        if payment_method == "card":
            body["payment_source"] = {
                "card": {
                    "number": self.test_card_number,
                    "expiry": self.test_card_expiry,
                    "name": "Sandbox Tester",
                    "billing_address": {"address_line_1": "1 Main St", "admin_area_2": "San Jose",
                                        "admin_area_1": "CA", "postal_code": "95131", "country_code": "US"},
                }
            }
        else:
            body["payment_source"] = {
                "paypal": {
                    "experience_context": {
                        "user_action": "PAY_NOW",
                        "return_url": "https://example.com/return",
                        "cancel_url": "https://example.com/cancel",
                    }
                }
            }
        return self.request("POST", "/v2/checkout/orders", body, mock_error)

    def get_order(self, order_id: str) -> ApiResponse:
        return self.request("GET", f"/v2/checkout/orders/{order_id}")

    def capture_order(self, order_id: str, mock_error: str | None = None) -> ApiResponse:
        return self.request("POST", f"/v2/checkout/orders/{order_id}/capture", {}, mock_error)

    def authorize_order(self, order_id: str, mock_error: str | None = None) -> ApiResponse:
        return self.request("POST", f"/v2/checkout/orders/{order_id}/authorize", {}, mock_error)

    # ----------------------------------------------------------- Payments v2
    def get_authorization(self, authorization_id: str) -> ApiResponse:
        return self.request("GET", f"/v2/payments/authorizations/{authorization_id}")

    def capture_authorization(
        self,
        authorization_id: str,
        amount: str | None = None,
        currency: str = "USD",
        final_capture: bool = True,
        mock_error: str | None = None,
    ) -> ApiResponse:
        body: dict[str, Any] = {"final_capture": final_capture}
        if amount:
            body["amount"] = {"currency_code": currency, "value": amount}
        return self.request("POST", f"/v2/payments/authorizations/{authorization_id}/capture", body, mock_error)

    def void_authorization(self, authorization_id: str, mock_error: str | None = None) -> ApiResponse:
        return self.request("POST", f"/v2/payments/authorizations/{authorization_id}/void", None, mock_error)

    def get_capture(self, capture_id: str) -> ApiResponse:
        return self.request("GET", f"/v2/payments/captures/{capture_id}")

    def refund_capture(
        self,
        capture_id: str,
        amount: str | None = None,
        currency: str = "USD",
        note: str | None = None,
        mock_error: str | None = None,
    ) -> ApiResponse:
        body: dict[str, Any] = {}
        if amount:
            body["amount"] = {"currency_code": currency, "value": amount}
        if note:
            body["note_to_payer"] = note
        return self.request("POST", f"/v2/payments/captures/{capture_id}/refund", body, mock_error)

    def get_refund(self, refund_id: str) -> ApiResponse:
        return self.request("GET", f"/v2/payments/refunds/{refund_id}")
