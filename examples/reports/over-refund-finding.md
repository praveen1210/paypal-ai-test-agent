# ❌ FAIL: After refunding 10 of a 20 USD capture, a refund request for 20 USD must be rejected rather than partially applied

- **Checks:** 18/23 passed
- **API steps:** 7
- **Model:** claude-haiku-5.5
- **Run:** 2026-11-08T18:38:08+00:00 → 2026-11-08T18:38:44+00:00

## Summary

The core business rule failed. After a valid 10.00 partial refund on a 20.00 capture, a second refund request for 20.00 was not rejected. PayPal returned HTTP 201 and created refund 02P44233KF644720T for 10.00 (the remaining balance), so the request was partially applied. The capture is now fully REFUNDED with total refunded 20.00. Setup steps passed: order 7X066593VK660805U was COMPLETED, capture 108361158K599311B was 20.00 COMPLETED, and the first 10.00 refund (2FS14489L8071434U) succeeded and left the capture PARTIALLY_REFUNDED.

## Findings

### [CRITICAL] Over-refund accepted and silently truncated to remaining balance (steps: S5, S6, S7)

After refund 2FS14489L8071434U (10.00) on capture 108361158K599311B (20.00), a refund request for 20.00 returned HTTP 201 instead of a 4xx REFUND_AMOUNT_EXCEEDED error. The refund created (02P44233KF644720T) is for 10.00, not 20.00, so the requested amount was reduced to the remaining balance without telling the caller. The capture is now REFUNDED with total_refunded_amount 20.00. The likely cause is that the refund handler caps the amount to the remaining refundable balance instead of validating the request against it and rejecting it. Developers should check the refund validation path in the sandbox integration and confirm whether this is a PayPal sandbox behaviour or a merchant-side or proxy-side bug. Business impact: a merchant or support agent who asks for 20.00 back gets 10.00 back with a success response, so the customer's expected refund amount and the books disagree, and the refund ledger no longer matches the request. Customers could be under-refunded without notice, and any reconciliation that assumes requested equals processed will break.

### [MAJOR] Over-refund test expectation not met (expected 4xx, got 201) (steps: S5)

The negative check required an error with REFUND_AMOUNT_EXCEEDED and the call returned 201 Created. The error-code check also failed because no details[] issue was returned. This is the same defect as above, shown at the API response level.


## Test plan

1. S1: create_order 20.00 USD card, intent CAPTURE (card charged at create; take capture id from purchase_units[0].payments)
2. S2: get_order to confirm COMPLETED and capture id
3. S3: get_capture to confirm 20.00 COMPLETED
4. S4: refund_capture 10.00 partial refund
5. S5: get_capture to confirm PARTIALLY_REFUNDED and 10.00 refunded
6. S6: refund_capture 20.00 with expect=error, expected_issue REFUND_AMOUNT_EXCEEDED (must be rejected)
7. S7: get_capture to confirm no extra refund was applied (still 10.00 refunded, 10.00 remaining)
8. S8: refund_capture 10.00 remaining succeeds only if state is consistent (optional confirmation)

## Steps

| Step | Call | Expect | HTTP | Debug ID | Checks |
|---|---|---|---|---|---|
| S1 | `POST /v2/checkout/orders` | success | 201 | f926386379268 | 5/5 |
| S2 | `GET /v2/payments/captures/108361158K599311B` | success | 200 | f4943563e91db | 2/2 |
| S3 | `POST /v2/payments/captures/108361158K599311B/refund` | success | 201 | f813701603235 | 3/3 |
| S4 | `GET /v2/payments/captures/108361158K599311B` | success | 200 | f550531d472f2 | 3/3 |
| S5 | `POST /v2/payments/captures/108361158K599311B/refund` | error | 201 | f405420858ada | 1/5 |
| S6 | `GET /v2/payments/captures/108361158K599311B` | success | 200 | f48038744d92d | 2/3 |
| S7 | `GET /v2/payments/refunds/02P44233KF644720T` | success | 200 | f8416565d9a58 | 2/2 |

## Checks

| | Step | Check | Expected | Actual | Source |
|---|---|---|---|---|---|
| ✅ | S1 | create_order returns HTTP 2xx | 2xx | 201 | auto |
| ✅ | S1 | Order id is returned | exists | 7X066593VK660805U | auto |
| ✅ | S1 | Order status is valid after create | ["CREATED", "APPROVED", "PAYER_ACTION_REQUIRED", "COMPLETED"] | COMPLETED | auto |
| ✅ | S1 | Order amount matches request | 20.00 | 20.00 | auto |
| ✅ | S1 | Order currency matches request | USD | USD | auto |
| ✅ | S2 | get_capture returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S2 | Fetched resource id matches | 108361158K599311B | 108361158K599311B | auto |
| ✅ | S3 | refund_capture returns HTTP 2xx | 2xx | 201 | auto |
| ✅ | S3 | Refund status is COMPLETED or PENDING | ["COMPLETED", "PENDING"] | COMPLETED | auto |
| ✅ | S3 | Refunded amount matches request | 10.00 | 10.00 | auto |
| ✅ | S4 | get_capture returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S4 | Fetched resource id matches | 108361158K599311B | 108361158K599311B | auto |
| ❌ | S5 | refund_capture is rejected with a 4xx error | 4xx | 201 | auto |
| ❌ | S5 | Error body has PayPal 'name' field | exists | <missing> | auto |
| ✅ | S5 | PayPal debug_id returned for support tracing (header or body) | exists | f405420858ada | auto |
| ❌ | S5 | Error issue code is REFUND_AMOUNT_EXCEEDED | REFUND_AMOUNT_EXCEEDED | [] | auto |
| ✅ | S6 | get_capture returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S6 | Fetched resource id matches | 108361158K599311B | 108361158K599311B | auto |
| ✅ | S7 | get_refund returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S7 | Fetched resource id matches | 02P44233KF644720T | 02P44233KF644720T | auto |
| ✅ | S4 | Capture is PARTIALLY_REFUNDED after the 10.00 partial refund | PARTIALLY_REFUNDED | PARTIALLY_REFUNDED | agent |
| ❌ | S5 | Over-refund of 20.00 after 10.00 refunded must return a 4xx error | 400 | 201 | agent |
| ❌ | S6 | Capture should still be PARTIALLY_REFUNDED (10.00 remaining) if the over-refu... | PARTIALLY_REFUNDED | REFUNDED | agent |
