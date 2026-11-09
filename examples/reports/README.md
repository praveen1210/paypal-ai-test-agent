# Sample reports

Real runs of the agent against the PayPal sandbox (Claude Haiku 5.5), each as Markdown, JSON and JUnit XML.
Card numbers are masked; IDs are sandbox-only.

| Report | Goal | Verdict |
|---|---|---|
| [partial-refund](partial-refund.md) | Test a partial refund on a captured order | ✅ PASS |
| [authorize-capture-void](authorize-capture-void.md) | Authorize 40, capture 25, void the rest, check the states | ✅ PASS |
| [declined-card](declined-card.md) | Simulate a declined card and check the error is handled | ✅ PASS |
| [over-refund-finding](over-refund-finding.md) | After refunding 10 of 20, a refund request for 20 must be rejected | ❌ FAIL: real finding |

The FAIL is the point of the last one: PayPal answered `201 COMPLETED` to a 20.00 refund request but refunded
only the remaining 10.00. See the main README, "What it found".
