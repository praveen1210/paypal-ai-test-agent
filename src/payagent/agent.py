"""The AI agent: turns a plain-English test goal into PayPal sandbox API calls via Claude tool use."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anthropic

from .config import Settings
from .models import RunResult
from .paypal_client import PayPalClient
from .tools import TOOL_DEFINITIONS, EventSink, ToolExecutor

SYSTEM_PROMPT = """\
You are a senior QA engineer testing a merchant's PayPal integration against the PayPal SANDBOX \
(Orders v2 and Payments v2 REST APIs). The user gives you a test goal in plain English. Your job:

1. Call record_plan with a short, ordered test plan (setup steps + the actual checks).
2. Execute the plan with the API tools, using IDs from earlier responses (order id -> capture id -> refund id).
   - Fund orders with payment_method="card" unless the goal explicitly needs PayPal-wallet approval.
   - If create_order already returns status COMPLETED, the card was processed at create time: take the \
capture/authorization id from purchase_units[0].payments instead of calling capture/authorize again.
   - For negative tests set expect="error" and, when you know it, expected_issue. Use mock_error only when \
the goal asks to simulate a processor/bank failure that cannot be triggered with real inputs.
   - Unless the goal itself is a negative test, ALSO include at least one negative test that probes the \
business rule under test (e.g. refund more than remains, capture an already-captured order, capture a voided \
authorization) with expect="error".
3. Every API step is validated automatically. Add assert_field checks for anything goal-specific the \
built-in checks don't cover (state transitions, remaining amounts, ids linking resources together). \
Re-read resources with get_* tools to verify state after changes. Only assert on paths you have actually seen \
in a response body; to check that a field is present use operator "exists". If one of your own assertions \
fails because the assertion was wrong (path or expectation), call retract_assertion with the reason. Never \
retract to hide real API behaviour; retractions are shown in the report.
4. Call finish with a plain-English summary and findings. For every failed check explain, for a developer, \
what probably went wrong, which step shows it (step ids), and the business impact. If everything passed, \
say what was proven and note any coverage gaps.

PayPal sandbox facts (verified):
- Card-funded orders are charged at create time. To simulate a card decline, pass mock_error \
(e.g. INSTRUMENT_DECLINED) on create_order. Mocks on capture_authorization return a bare 403 with no body, \
so don't use them there.
- PayPal lets a merchant capture up to 115% of an authorization (at most +75 USD above it), across one or more \
captures. An over-capture negative test must exceed that limit, otherwise PayPal correctly accepts it.
- Documented issue codes: ORDER_ALREADY_CAPTURED, CAPTURE_FULLY_REFUNDED (refund after a full refund), \
REFUND_AMOUNT_EXCEEDED (refund larger than what remains), REFUND_CAPTURE_CURRENCY_MISMATCH, PREVIOUSLY_CAPTURED, \
MAX_CAPTURE_AMOUNT_EXCEEDED (capture above the allowed limit), \
PREVIOUSLY_VOIDED, AUTHORIZATION_VOIDED, CANNOT_BE_ZERO_OR_NEGATIVE, INSTRUMENT_DECLINED, TRANSACTION_REFUSED. \
Set expected_issue only when one of these (or a code you saw in a response) clearly applies; otherwise leave it out.

Rules: Never invent IDs or response data. Keep amounts small (under 100.00). Don't repeat a step that already \
gave a clear answer. If authentication fails, stop and call finish explaining the setup problem.\
"""

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class PaymentTestAgent:
    def __init__(
        self,
        settings: Settings,
        paypal: PayPalClient,
        client: anthropic.Anthropic | None = None,
        on_event: EventSink | None = None,
    ) -> None:
        self.settings = settings
        self.paypal = paypal
        self.client = client or anthropic.Anthropic()
        self.on_event = on_event or (lambda _kind, _data: None)

    def _create(self, messages: list[dict[str, Any]]) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.settings.anthropic_model,
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "tools": TOOL_DEFINITIONS,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.settings.anthropic_effort},
        }
        if self.settings.anthropic_fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return self.client.beta.messages.create(**kwargs)

    def run(self, goal: str) -> RunResult:
        result = RunResult(goal=goal, started_at=_now(), model=self.settings.anthropic_model)
        executor = ToolExecutor(self.paypal, result, self.on_event)
        messages: list[dict[str, Any]] = [{"role": "user", "content": f"Test goal: {goal}"}]
        nudged = False
        usage = {"input_tokens": 0, "output_tokens": 0}

        try:
            for _turn in range(self.settings.max_turns):
                response = self._create(messages)
                usage["input_tokens"] += getattr(response.usage, "input_tokens", 0) or 0
                usage["output_tokens"] += getattr(response.usage, "output_tokens", 0) or 0
                messages.append({"role": "assistant", "content": response.content})

                for block in response.content:
                    if block.type == "text" and block.text.strip():
                        self.on_event("agent_note", {"text": block.text})

                if response.stop_reason == "refusal":
                    result.agent_error = f"Model declined the request ({getattr(response, 'stop_details', None)})"
                    break
                if response.stop_reason == "max_tokens":
                    result.agent_error = "Model response hit max_tokens before finishing."
                    break
                if response.stop_reason == "pause_turn":
                    continue

                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if not tool_uses:
                    if executor.finished or nudged:
                        break
                    nudged = True
                    messages.append({"role": "user", "content":
                                     "Continue the test. When done, call the finish tool with your report."})
                    continue

                tool_results = []
                for tool_use in tool_uses:
                    content, is_error = executor.execute(tool_use.name, dict(tool_use.input or {}))
                    tool_results.append({"type": "tool_result", "tool_use_id": tool_use.id,
                                         "content": content, "is_error": is_error})
                messages.append({"role": "user", "content": tool_results})

                if executor.finished:
                    break
            else:
                result.agent_error = f"Agent stopped after {self.settings.max_turns} turns without finishing."
        except anthropic.AuthenticationError:
            result.agent_error = "Anthropic API key is missing or invalid (ANTHROPIC_API_KEY)."
        except anthropic.RateLimitError:
            result.agent_error = "Anthropic rate limit hit; retry in a minute."
        except anthropic.APIStatusError as exc:
            result.agent_error = f"Anthropic API error {exc.status_code}: {exc.message}"
        except anthropic.APIConnectionError as exc:
            result.agent_error = f"Could not reach the Anthropic API: {exc}"

        if not executor.finished and not result.summary:
            result.summary = "The agent did not complete its report; see steps and checks below."
        result.usage = usage
        result.finished_at = _now()
        self.on_event("finished", {"result": result})
        return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
