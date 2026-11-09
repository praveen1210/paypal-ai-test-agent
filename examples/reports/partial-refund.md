# ✅ PASS: Test a partial refund on a captured order

- **Checks:** 31/31 passed
- **API steps:** 9
- **Model:** claude-haiku-5.5
- **Run:** 2026-11-09T16:47:52+00:00 → 2026-11-09T16:48:29+00:00

## Summary

Partial refund on a captured order behaves correctly in the PayPal sandbox. A 20.00 USD card-funded order (order 603965450M1249740, capture 1G2950341L0926923) was partially refunded 8.00 (refund 83R28259SF490483K, COMPLETED). The capture moved to PARTIALLY_REFUNDED. An over-refund of 13.00 against 12.00 remaining was rejected with REFUND_AMOUNT_EXCEEDED. A refund of the remaining 12.00 succeeded (refund 8LH69773LF956593X), cumulative total refunded reached 20.00, and the capture became REFUNDED. A further refund attempt was rejected with CAPTURE_FULLY_REFUNDED. All built-in and goal-specific assertions passed.

## Findings

### [INFO] Partial refund flow works as expected (steps: S3, S4, S5)

An 8.00 partial refund on a 20.00 capture returned COMPLETED, the capture status changed to PARTIALLY_REFUNDED, and the refund's total_refunded_amount reported 8.00. Verified via S3, S4, S5.

### [INFO] Over-refund correctly rejected (steps: S6)

Refunding 13.00 when only 12.00 remained returned HTTP 422 with REFUND_AMOUNT_EXCEEDED, as documented.

### [INFO] Remaining balance refund and full-refund state correct (steps: S7, S8, S9)

Refunding the exact remaining 12.00 succeeded with cumulative total 20.00. The capture then moved to REFUNDED, and a further refund was rejected with CAPTURE_FULLY_REFUNDED.

### [INFO] Coverage gaps

Not covered: refunds in a different currency (REFUND_CAPTURE_CURRENCY_MISMATCH), refunds of zero or negative amounts, idempotency via PayPal-Request-Id on retried refunds, refunds on PayPal-wallet (non-card) orders, and the get_order view of refund status. The test also did not check the 'up' order link or the order-level status after refund.


## Test plan

1. Create a card-funded order for 20.00 USD with intent CAPTURE; confirm it is COMPLETED and note capture id from purchase_units[0].payments.captures
2. GET the capture to confirm status COMPLETED and amount 20.00
3. Partial refund 8.00 USD on the capture; verify refund COMPLETED and id returned
4. GET the refund to confirm amount 8.00
5. GET the capture to confirm status PARTIALLY_REFUNDED
6. Negative test: refund 13.00 more (exceeds remaining 12.00) expecting REFUND_AMOUNT_EXCEEDED
7. Negative test: refund remaining 12.00 succeeds, then full refund attempt fails with CAPTURE_FULLY_REFUNDED (optional final check)

## Steps

| Step | Call | Expect | HTTP | Debug ID | Checks |
|---|---|---|---|---|---|
| S1 | `POST /v2/checkout/orders` | success | 201 | f1478930be138 | 5/5 |
| S2 | `GET /v2/payments/captures/1G2950341L0926923` | success | 200 | f251533448cc2 | 2/2 |
| S3 | `POST /v2/payments/captures/1G2950341L0926923/refund` | success | 201 | f106313a8beee | 3/3 |
| S4 | `GET /v2/payments/refunds/83R28259SF490483K` | success | 200 | f392733fe8838 | 3/3 |
| S5 | `GET /v2/payments/captures/1G2950341L0926923` | success | 200 | f2085625a929b | 3/3 |
| S6 | `POST /v2/payments/captures/1G2950341L0926923/refund` | error | 422 | f662214e4f98a | 4/4 |
| S7 | `POST /v2/payments/captures/1G2950341L0926923/refund` | success | 201 | f393991882b8a | 4/4 |
| S8 | `POST /v2/payments/captures/1G2950341L0926923/refund` | error | 422 | f514302904452 | 4/4 |
| S9 | `GET /v2/payments/captures/1G2950341L0926923` | success | 200 | f674833766d73 | 3/3 |

## Checks

| | Step | Check | Expected | Actual | Source |
|---|---|---|---|---|---|
| ✅ | S1 | create_order returns HTTP 2xx | 2xx | 201 | auto |
| ✅ | S1 | Order id is returned | exists | 603965450M1249740 | auto |
| ✅ | S1 | Order status is valid after create | ["CREATED", "APPROVED", "PAYER_ACTION_REQUIRED", "COMPLETED"] | COMPLETED | auto |
| ✅ | S1 | Order amount matches request | 20.00 | 20.00 | auto |
| ✅ | S1 | Order currency matches request | USD | USD | auto |
| ✅ | S2 | get_capture returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S2 | Fetched resource id matches | 1G2950341L0926923 | 1G2950341L0926923 | auto |
| ✅ | S3 | refund_capture returns HTTP 2xx | 2xx | 201 | auto |
| ✅ | S3 | Refund status is COMPLETED or PENDING | ["COMPLETED", "PENDING"] | COMPLETED | auto |
| ✅ | S3 | Refunded amount matches request | 8.00 | 8.00 | auto |
| ✅ | S4 | get_refund returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S4 | Fetched resource id matches | 83R28259SF490483K | 83R28259SF490483K | auto |
| ✅ | S5 | get_capture returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S5 | Fetched resource id matches | 1G2950341L0926923 | 1G2950341L0926923 | auto |
| ✅ | S6 | refund_capture is rejected with a 4xx error | 4xx | 422 | auto |
| ✅ | S6 | Error body has PayPal 'name' field | exists | UNPROCESSABLE_ENTITY | auto |
| ✅ | S6 | PayPal debug_id returned for support tracing (header or body) | exists | f662214e4f98a | auto |
| ✅ | S6 | Error issue code is REFUND_AMOUNT_EXCEEDED | REFUND_AMOUNT_EXCEEDED | ["REFUND_AMOUNT_EXCEEDED"] | auto |
| ✅ | S7 | refund_capture returns HTTP 2xx | 2xx | 201 | auto |
| ✅ | S7 | Refund status is COMPLETED or PENDING | ["COMPLETED", "PENDING"] | COMPLETED | auto |
| ✅ | S7 | Refunded amount matches request | 12.00 | 12.00 | auto |
| ✅ | S8 | refund_capture is rejected with a 4xx error | 4xx | 422 | auto |
| ✅ | S8 | Error body has PayPal 'name' field | exists | UNPROCESSABLE_ENTITY | auto |
| ✅ | S8 | PayPal debug_id returned for support tracing (header or body) | exists | f514302904452 | auto |
| ✅ | S8 | Error issue code is CAPTURE_FULLY_REFUNDED | CAPTURE_FULLY_REFUNDED | ["CAPTURE_FULLY_REFUNDED"] | auto |
| ✅ | S9 | get_capture returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S9 | Fetched resource id matches | 1G2950341L0926923 | 1G2950341L0926923 | auto |
| ✅ | S5 | Capture status is PARTIALLY_REFUNDED after an 8.00 refund on a 20.00 capture | PARTIALLY_REFUNDED | PARTIALLY_REFUNDED | agent |
| ✅ | S4 | First refund reports total refunded 8.00 | 8.0 | 8.00 | agent |
| ✅ | S7 | Cumulative total refunded is 20.00 after the 12.00 refund | 20.0 | 20.00 | agent |
| ✅ | S9 | Capture status is REFUNDED once fully refunded | REFUNDED | REFUNDED | agent |
