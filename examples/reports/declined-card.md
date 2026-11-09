# ✅ PASS: Simulate a declined card at capture time and check the error is handled

- **Checks:** 20/20 passed
- **API steps:** 5
- **Model:** claude-haiku-5.5
- **Run:** 2026-11-09T16:53:06+00:00 → 2026-11-09T16:53:29+00:00

## Summary

Tested how a declined card is handled at capture time in the PayPal sandbox. Card orders are charged at create time, so a true capture-time decline was simulated by calling capture_order on an existing order with the INSTRUMENT_DECLINED mock. PayPal rejected it with HTTP 422, issue INSTRUMENT_DECLINED and a debug_id, which is the expected error shape. The create-time decline control (S3) was also rejected with the same 422/INSTRUMENT_DECLINED response. The previously successful order (0AB67962YR4285836) and its capture (16S56782J6857735Y) remained COMPLETED with the original $10.00 amount, so the failed attempt did not corrupt existing state.

## Findings

### [INFO] Declined capture returns a structured, handleable error (steps: S2, S3)

S2 returned HTTP 422 UNPROCESSABLE_ENTITY with details[0].issue=INSTRUMENT_DECLINED, a description, and a debug_id. The error is machine-readable and includes a support trace id, so the merchant can branch on the issue code and show a decline message. The same error shape appeared on create-time decline (S3).

### [INFO] Existing captured order is unaffected by a declined capture attempt (steps: S4, S5)

After the declined capture (S2), S4 and S5 show the order and capture still COMPLETED for $10.00 with no refund or reversal. The failed attempt did not change state.


## Test plan

1. S1: Create a baseline card order (intent CAPTURE, 10.00 USD) to confirm the sandbox works and see how payments are represented.
2. S2: Simulate a declined card at capture time: call capture_order on a fresh order with mock_error INSTRUMENT_DECLINED, expecting an error.
3. S3: Negative control: attempt create_order with mock_error INSTRUMENT_DECLINED (card decline at create) and confirm it is rejected with no capture recorded.
4. S4: Re-read the baseline order with get_order to verify it is not altered by the declined attempts.
5. S5: Assert the decline response carries INSTRUMENT_DECLINED / an error status and the order does not transition to COMPLETED.

## Steps

| Step | Call | Expect | HTTP | Debug ID | Checks |
|---|---|---|---|---|---|
| S1 | `POST /v2/checkout/orders` | success | 201 | ca57e5507f905 | 5/5 |
| S2 | `POST /v2/checkout/orders/0AB67962YR4285836/capture` | error | 422 | ca57e553248a2 | 5/5 |
| S3 | `POST /v2/checkout/orders` | error | 422 | ca57e55387939 | 4/4 |
| S4 | `GET /v2/checkout/orders/0AB67962YR4285836` | success | 200 | ca57e55494cf0 | 3/3 |
| S5 | `GET /v2/payments/captures/16S56782J6857735Y` | success | 200 | ca57e554e9b7f | 3/3 |

## Checks

| | Step | Check | Expected | Actual | Source |
|---|---|---|---|---|---|
| ✅ | S1 | create_order returns HTTP 2xx | 2xx | 201 | auto |
| ✅ | S1 | Order id is returned | exists | 0AB67962YR4285836 | auto |
| ✅ | S1 | Order status is valid after create | ["CREATED", "APPROVED", "PAYER_ACTION_REQUIRED", "COMPLETED"] | COMPLETED | auto |
| ✅ | S1 | Order amount matches request | 10.00 | 10.00 | auto |
| ✅ | S1 | Order currency matches request | USD | USD | auto |
| ✅ | S2 | capture_order is rejected with a 4xx error | 4xx | 422 | auto |
| ✅ | S2 | Error body has PayPal 'name' field | exists | UNPROCESSABLE_ENTITY | auto |
| ✅ | S2 | PayPal debug_id returned for support tracing (header or body) | exists | ca57e553248a2 | auto |
| ✅ | S2 | Error issue code is INSTRUMENT_DECLINED | INSTRUMENT_DECLINED | ["INSTRUMENT_DECLINED"] | auto |
| ✅ | S3 | create_order is rejected with a 4xx error | 4xx | 422 | auto |
| ✅ | S3 | Error body has PayPal 'name' field | exists | UNPROCESSABLE_ENTITY | auto |
| ✅ | S3 | PayPal debug_id returned for support tracing (header or body) | exists | ca57e55387939 | auto |
| ✅ | S3 | Error issue code is INSTRUMENT_DECLINED | INSTRUMENT_DECLINED | ["INSTRUMENT_DECLINED"] | auto |
| ✅ | S4 | get_order returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S4 | Fetched resource id matches | 0AB67962YR4285836 | 0AB67962YR4285836 | auto |
| ✅ | S5 | get_capture returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S5 | Fetched resource id matches | 16S56782J6857735Y | 16S56782J6857735Y | auto |
| ✅ | S2 | Capture-time decline returns INSTRUMENT_DECLINED issue code | INSTRUMENT_DECLINED | INSTRUMENT_DECLINED | agent |
| ✅ | S4 | Baseline order remains COMPLETED after declined capture attempt | COMPLETED | COMPLETED | agent |
| ✅ | S5 | Capture remains COMPLETED and not refunded/reversed after declined attempt | COMPLETED | COMPLETED | agent |
