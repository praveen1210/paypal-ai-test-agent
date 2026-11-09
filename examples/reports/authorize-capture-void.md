# ✅ PASS: Authorize 40 USD, capture 25 as a partial capture, then void the rest and check the states

- **Checks:** 30/30 passed
- **API steps:** 8
- **Model:** claude-haiku-5.5
- **Run:** 2026-11-09T16:49:29+00:00 → 2026-11-09T16:50:05+00:00

## Summary

Tested the authorize 40 USD → partial capture 25 USD → void remainder flow in the PayPal sandbox. All checks passed. The order 67N85550R90517011 was card-funded at create time (status COMPLETED, authorization 53984335H1838011A CREATED for 40.00). A 25.00 partial capture (6WG29562W48281115, final_capture=false, COMPLETED) moved the authorization to PARTIALLY_CAPTURED. Voiding the remainder moved it to VOIDED. Negative tests passed: a second void returned PREVIOUSLY_VOIDED (422), and capturing the remaining 15.00 after the void returned AUTHORIZATION_VOIDED (422). The order view shows the authorization VOIDED and the 25.00 capture COMPLETED, and the capture links back to the authorization.

## Findings

### [INFO] Partial capture then void behaves per spec (steps: S1, S2, S3, S4, S5, S6, S7, S8)

Authorization 40.00 → partial capture 25.00 (status PARTIALLY_CAPTURED) → void (status VOIDED). The 25.00 capture remains COMPLETED and is retained. Both negative tests returned the documented issue codes (PREVIOUSLY_VOIDED, AUTHORIZATION_VOIDED).

### [INFO] Observation: authorization amount still reports 40.00 after partial capture and void (steps: S3, S4, S8)

The authorization resource's amount field stays at 40.00 after the 25.00 capture and the void. This is probably the originally authorized amount rather than a remaining balance, so it is not a defect, but integrators should derive the remaining balance from captures rather than from this field.

### [INFO] Coverage gaps (steps: S1)

Not tested: a second partial capture before voiding, a capture above the authorized amount (MAX_CAPTURE_AMOUNT_EXCEEDED), refund of the 25.00 capture, the 'authorize' step as a separate API call (the card order was authorized at create time so authorize_order was skipped), and PayPal-wallet flows.


## Test plan

1. S1: Create a 40.00 USD AUTHORIZE order funded by sandbox card; confirm authorization id is returned.
2. S2: Authorize the order if not already authorized; capture the authorization ID.
3. S3: Partially capture 25.00 USD from the authorization (final_capture=false); verify captured amount.
4. S4: Get authorization to confirm state after partial capture (remaining 15.00 open).
5. S5: Void the remaining authorization; verify VOIDED state.
6. S6: Negative tests: second void (expect PREVIOUSLY_VOIDED) and capture of 15.00 after void (expect AUTHORIZATION_VOIDED).
7. S7: Re-read authorization and order to confirm final states; finish.

## Steps

| Step | Call | Expect | HTTP | Debug ID | Checks |
|---|---|---|---|---|---|
| S1 | `POST /v2/checkout/orders` | success | 201 | ca57e4fc29955 | 5/5 |
| S2 | `POST /v2/payments/authorizations/53984335H1838011A/capture` | success | 201 | ca57e4fe1283c | 4/4 |
| S3 | `GET /v2/payments/authorizations/53984335H1838011A` | success | 200 | ca57e4ff84cd9 | 3/3 |
| S4 | `POST /v2/payments/authorizations/53984335H1838011A/void` | success | 200 | ca57e500b0978 | 3/3 |
| S5 | `POST /v2/payments/authorizations/53984335H1838011A/void` | error | 422 | ca57e50259ec4 | 4/4 |
| S6 | `POST /v2/payments/authorizations/53984335H1838011A/capture` | error | 422 | ca57e502a6b2d | 4/4 |
| S7 | `GET /v2/payments/captures/6WG29562W48281115` | success | 200 | ca57e502f3838 | 3/3 |
| S8 | `GET /v2/checkout/orders/67N85550R90517011` | success | 200 | ca57e50339bd4 | 4/4 |

## Checks

| | Step | Check | Expected | Actual | Source |
|---|---|---|---|---|---|
| ✅ | S1 | create_order returns HTTP 2xx | 2xx | 201 | auto |
| ✅ | S1 | Order id is returned | exists | 67N85550R90517011 | auto |
| ✅ | S1 | Order status is valid after create | ["CREATED", "APPROVED", "PAYER_ACTION_REQUIRED", "COMPLETED"] | COMPLETED | auto |
| ✅ | S1 | Order amount matches request | 40.00 | 40.00 | auto |
| ✅ | S1 | Order currency matches request | USD | USD | auto |
| ✅ | S2 | capture_authorization returns HTTP 2xx | 2xx | 201 | auto |
| ✅ | S2 | Capture status is COMPLETED | COMPLETED | COMPLETED | auto |
| ✅ | S2 | Captured amount matches request | 25.00 | 25.00 | auto |
| ✅ | S3 | get_authorization returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S3 | Fetched resource id matches | 53984335H1838011A | 53984335H1838011A | auto |
| ✅ | S4 | void_authorization returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S4 | Authorization status is VOIDED | VOIDED | VOIDED | auto |
| ✅ | S5 | void_authorization is rejected with a 4xx error | 4xx | 422 | auto |
| ✅ | S5 | Error body has PayPal 'name' field | exists | UNPROCESSABLE_ENTITY | auto |
| ✅ | S5 | PayPal debug_id returned for support tracing (header or body) | exists | ca57e50259ec4 | auto |
| ✅ | S5 | Error issue code is PREVIOUSLY_VOIDED | PREVIOUSLY_VOIDED | ["PREVIOUSLY_VOIDED"] | auto |
| ✅ | S6 | capture_authorization is rejected with a 4xx error | 4xx | 422 | auto |
| ✅ | S6 | Error body has PayPal 'name' field | exists | UNPROCESSABLE_ENTITY | auto |
| ✅ | S6 | PayPal debug_id returned for support tracing (header or body) | exists | ca57e502a6b2d | auto |
| ✅ | S6 | Error issue code is AUTHORIZATION_VOIDED | AUTHORIZATION_VOIDED | ["AUTHORIZATION_VOIDED"] | auto |
| ✅ | S7 | get_capture returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S7 | Fetched resource id matches | 6WG29562W48281115 | 6WG29562W48281115 | auto |
| ✅ | S8 | get_order returns HTTP 2xx | 2xx | 200 | auto |
| ✅ | S8 | Fetched resource id matches | 67N85550R90517011 | 67N85550R90517011 | auto |
| ✅ | S3 | Authorization is PARTIALLY_CAPTURED after 25.00 partial capture | PARTIALLY_CAPTURED | PARTIALLY_CAPTURED | agent |
| ✅ | S4 | Authorization is VOIDED after voiding the remainder | VOIDED | VOIDED | agent |
| ✅ | S2 | Partial capture is not marked as final_capture | false | false | agent |
| ✅ | S8 | Order view shows the authorization as VOIDED | VOIDED | VOIDED | agent |
| ✅ | S8 | Order view shows the 25.00 capture still COMPLETED alongside the voided remai... | 25.0 | 25.00 | agent |
| ✅ | S7 | Capture links back to the original authorization | 53984335H1838011A | 53984335H1838011A | agent |
