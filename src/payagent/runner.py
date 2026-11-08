"""Wires settings, PayPal client and agent together (shared by CLI and web)."""

from __future__ import annotations

from .agent import PaymentTestAgent
from .config import Settings
from .fake_paypal import FakePayPalClient
from .models import RunResult
from .paypal_client import PayPalClient
from .tools import EventSink


def build_paypal(settings: Settings) -> PayPalClient:
    settings.assert_paypal_ready()
    if settings.use_fake_paypal:
        return FakePayPalClient()
    return PayPalClient(
        settings.paypal_client_id,
        settings.paypal_client_secret,
        settings.paypal_base_url,
        settings.test_card_number,
        settings.test_card_expiry,
    )


def run_goal(goal: str, settings: Settings | None = None, on_event: EventSink | None = None) -> RunResult:
    settings = settings or Settings.from_env()
    agent = PaymentTestAgent(settings, build_paypal(settings), on_event=on_event)
    return agent.run(goal)
