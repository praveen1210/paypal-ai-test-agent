"""Settings loaded from environment variables / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    paypal_client_id: str
    paypal_client_secret: str
    paypal_base_url: str
    test_card_number: str
    test_card_expiry: str
    anthropic_model: str
    anthropic_effort: str
    anthropic_fallbacks: bool
    max_turns: int
    reports_dir: str
    use_fake_paypal: bool

    @classmethod
    def from_env(cls) -> Settings:
        # The project's .env wins over inherited shell variables (e.g. a stray ANTHROPIC_BASE_URL);
        # hosted deploys have no .env, so their dashboard env vars apply unchanged.
        load_dotenv(override=True)
        # A blank ANTHROPIC_BASE_URL (e.g. an empty field in Render or .env) would break the SDK; treat it as unset.
        if not os.environ.get("ANTHROPIC_BASE_URL", "x").strip():
            os.environ.pop("ANTHROPIC_BASE_URL", None)
        return cls(
            paypal_client_id=os.getenv("PAYPAL_CLIENT_ID", ""),
            paypal_client_secret=os.getenv("PAYPAL_CLIENT_SECRET", ""),
            paypal_base_url=os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/"),
            test_card_number=os.getenv("PAYPAL_TEST_CARD_NUMBER", "4111111111111111"),
            test_card_expiry=os.getenv("PAYPAL_TEST_CARD_EXPIRY", "2030-12"),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5"),
            anthropic_effort=os.getenv("ANTHROPIC_EFFORT", "medium"),
            anthropic_fallbacks=os.getenv("ANTHROPIC_FALLBACKS", "default").strip().lower() != "off",
            max_turns=int(os.getenv("AGENT_MAX_TURNS", "25")),
            reports_dir=os.getenv("REPORTS_DIR", "reports"),
            use_fake_paypal=_bool(os.getenv("PAYAGENT_FAKE_PAYPAL")),
        )

    def assert_paypal_ready(self) -> None:
        if "api-m.paypal.com" in self.paypal_base_url:
            raise RuntimeError("Refusing to run against PayPal LIVE. Use https://api-m.sandbox.paypal.com")
        if not self.use_fake_paypal and not (self.paypal_client_id and self.paypal_client_secret):
            raise RuntimeError(
                "PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set. Fill .env or set PAYAGENT_FAKE_PAYPAL=1."
            )
