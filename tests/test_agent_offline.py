"""End-to-end agent loop with a scripted stand-in for Claude and the fake PayPal. No network."""

import dataclasses
import json
from types import SimpleNamespace

from payagent.agent import PaymentTestAgent
from payagent.config import Settings
from payagent.fake_paypal import FakePayPalClient
from payagent.report import to_markdown


def _tool(name, **inp):
    return SimpleNamespace(type="tool_use", id=f"tu_{name}_{id(inp)}", name=name, input=inp)


def _last_result(messages):
    for block in messages[-1]["content"]:
        if block.get("type") == "tool_result" and block["content"].startswith("{"):
            return json.loads(block["content"])
    return {}


class ScriptedClaude:
    """Plays the role of the model: plan -> create -> double capture -> partial refund -> over-refund -> finish."""

    def __init__(self):
        self.turn = 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        msgs = kwargs["messages"]
        self.turn += 1
        prev = _last_result(msgs) if self.turn > 1 else {}
        body = json.loads(prev["response_body"]) if prev.get("response_body") else {}
        if self.turn == 1:
            blocks = [_tool("record_plan", steps=["create", "capture", "refund 4.00", "over-refund"])]
        elif self.turn == 2:
            blocks = [_tool("create_order", amount="10.00", payment_method="card")]
        elif self.turn == 3:
            # Card orders are captured at create time, so a second capture must be rejected.
            assert body["status"] == "COMPLETED"
            self.capture_id = body["purchase_units"][0]["payments"]["captures"][0]["id"]
            blocks = [_tool("capture_order", order_id=body["id"], expect="error",
                            expected_issue="ORDER_ALREADY_CAPTURED")]
        elif self.turn == 4:
            blocks = [_tool("refund_capture", capture_id=self.capture_id, amount="4.00")]
        elif self.turn == 5:
            blocks = [_tool("refund_capture", capture_id=self.capture_id, amount="7.00", expect="error",
                            expected_issue="REFUND_AMOUNT_EXCEEDED")]
        elif self.turn == 6:
            blocks = [_tool("get_capture", capture_id=self.capture_id)]
        elif self.turn == 7:
            blocks = [_tool("assert_field", step_id="S5", path="status", operator="equals",
                            expected="PARTIALLY_REFUNDED", description="Capture is PARTIALLY_REFUNDED")]
        else:
            blocks = [_tool("finish", summary="Partial refund works; over-refund rejected.", findings=[])]
        return SimpleNamespace(content=blocks, stop_reason="tool_use",
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_partial_refund_flow_passes():
    settings = dataclasses.replace(Settings.from_env(), use_fake_paypal=True, max_turns=15)
    events = []
    agent = PaymentTestAgent(settings, FakePayPalClient(), client=ScriptedClaude(),
                             on_event=lambda k, d: events.append(k))
    result = agent.run("test a partial refund on a captured order")

    assert result.agent_error is None
    assert [s.tool for s in result.steps] == ["create_order", "capture_order", "refund_capture",
                                              "refund_capture", "get_capture"]
    failed = [c for c in result.checks if not c.passed]
    assert failed == [], failed
    assert result.verdict == "PASS"
    assert "plan" in events and "finished" in events
    assert "PASS" in to_markdown(result)
