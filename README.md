# AI Payment Test Agent for PayPal

You describe a payment test in plain English, e.g. **"test a partial refund on a captured order"**. An AI agent
built on Claude plans the test and runs real **PayPal sandbox** API calls
(OAuth → create order → capture → refund → re-read state). Every response is validated, and you get a
**pass/fail report** with plain-English explanations of any bugs.

Most PayPal + AI projects build shopping bots. This one is aimed at the QA engineers who have to prove that a
payment integration works before it goes live.

```
"Verify I cannot refund more than the captured amount"
        │
        ▼
  Claude (tool use) ── record_plan ─▶ create_order ─▶ capture_order ─▶ refund_capture(expect=error) ─▶ finish
        │                                   │
        │                                   ▼
        │                         PayPal Sandbox REST APIs
        ▼                                   │
  Deterministic validator ◀─────────────────┘   (status codes, money math, error schema, state transitions)
        │
        ▼
  Report: PASS / FAIL / INCONCLUSIVE  +  findings  +  per-step PayPal debug IDs   (Markdown + JSON + web UI)
```

## How it works

| Piece | File | What it does |
|---|---|---|
| PayPal client | `src/payagent/paypal_client.py` | OAuth2 client-credentials (cached token), Orders v2 (create / get / capture / authorize), Payments v2 (captures, authorizations, refunds). It returns errors as data instead of raising, so negative tests work. Supports `PayPal-Mock-Response` negative testing and sends a `PayPal-Request-Id` on every call. |
| AI agent | `src/payagent/agent.py` | Claude tool-use loop. It turns the goal into a plan, calls the API tools with IDs chained from earlier responses, adds goal-specific assertions, and writes the findings. |
| Tools | `src/payagent/tools.py` | The tool schemas Claude sees and the executor that runs them. Each API call becomes a numbered step (`S1`, `S2`, …). |
| Validator | `src/payagent/validator.py` | **The AI decides what to test; code decides pass/fail.** Built-in rules check every step: 2xx, amounts match, capture/refund status, and the PayPal error schema plus `issue` code for `expect="error"` steps. The agent can also add its own checks through `assert_field` (JSON-path + operator). |
| Report | `src/payagent/report.py` | Markdown and JSON reports in `reports/`. Card numbers are masked. |
| Fake PayPal | `src/payagent/fake_paypal.py` | An in-memory sandbox stand-in for tests and offline demos (`--fake`). |
| CLI / Web | `cli.py`, `web.py`, `static/index.html` | `payagent "<goal>"` (exit code 0/1/2 for CI) and a one-page web UI with a JSON API. |

### AI tools used
- **Claude** with tool use and adaptive thinking is the planning and reasoning engine. It turns English into API
  sequences and explains failures. The demo runs **Claude Haiku 5.5** through the Experiential Labs gateway
  (Anthropic Messages API); any Claude model works by changing `ANTHROPIC_MODEL`.
- **Claude Code** was used to scaffold and develop this repository.

## Setup

Prerequisites: Python 3.10+, a PayPal developer account, and an Anthropic API key.

1. **PayPal sandbox app**: go to [developer.paypal.com](https://developer.paypal.com) → Apps & Credentials → **Sandbox** →
   Create App (Merchant). Copy the **Client ID** and **Secret**.
2. **Anthropic key**: [console.anthropic.com](https://console.anthropic.com) → API Keys.
3. Install:

```bash
git clone https://github.com/<you>/paypal-ai-test-agent.git
cd paypal-ai-test-agent
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, ANTHROPIC_API_KEY
```

`.env` is gitignored, so never commit real keys. The client refuses to run against PayPal **live** URLs.

## Run

CLI:

```bash
payagent "test a partial refund on a captured order"
payagent "verify I cannot refund more than the captured amount"
payagent "authorize 40 USD, capture 25, then void the rest and check the states"
payagent "simulate a declined card at capture time" --effort high
payagent "capture the same order twice must fail" --fake     # offline: no PayPal keys needed
```

Exit codes: `0` PASS, `1` FAIL, `2` INCONCLUSIVE/setup error, so the CLI can run as a Jenkins/Azure DevOps step.
Reports are written to `reports/<timestamp>-<goal>.md|.json`.

Regression suite (every goal in `examples/goals.txt`, summary table at the end, exit 0 only if all pass):

```bash
python scripts/run_suite.py
```

Web UI (the plan, each API call and each check stream in live while the agent works):

```bash
uvicorn payagent.web:app --reload
# open http://127.0.0.1:8000
```

API:
- `GET /api/run/stream?goal=...&fake=false` is a Server-Sent Events stream: `plan`, `step_started`,
  `step_finished`, `check`, `agent_note`, then a final `result` (or `error`).
- `POST /api/run {"goal": "...", "fake": false}` returns the full report JSON plus `markdown` in one response.

Values in `.env` take priority over variables already set in your shell.

Tests (offline, no keys):

```bash
pytest
ruff check .
```

## Deploy (Render)

`render.yaml` is included. Create a new **Blueprint** on Render pointing to this repo, then set
`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` and `ANTHROPIC_API_KEY` in the dashboard.

## Notes and limits
- Card-funded orders use a sandbox test card (`PAYPAL_TEST_CARD_NUMBER`), so they complete with no buyer clicks.
  In the sandbox, a card order with intent `CAPTURE` is captured at create time (status `COMPLETED`); the agent
  knows this. If you get `PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING`, your sandbox business account can't take cards:
  create a **United States** sandbox business account and a new app linked to it.
- Any Anthropic Messages-compatible endpoint works: set `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` and
  `ANTHROPIC_MODEL` (see `.env.example` for a gateway example).
- `payment_method="paypal"` orders need a sandbox **buyer** to approve them in the browser. The CLI prints the
  link and waits (`wait_for_buyer_approval`).
- The fake PayPal models common rules only. The real sandbox is the source of truth.

## License

[MIT](LICENSE)
