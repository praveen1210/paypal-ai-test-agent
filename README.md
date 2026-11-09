# AI Payment Test Agent for PayPal

[![CI](https://github.com/praveen1210/paypal-ai-test-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/praveen1210/paypal-ai-test-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

You describe a payment test in plain English, e.g. **"test a partial refund on a captured order"**. An AI agent
built on Claude plans the test and runs real **PayPal sandbox** API calls
(OAuth → create order → capture → refund → re-read state). Every response is validated, and you get a
**pass/fail report** with plain-English explanations of any bugs, as Markdown, JSON and **JUnit XML** for
Jenkins, Azure DevOps or GitHub Actions.

Most PayPal + AI projects build shopping bots. This one is aimed at the QA engineers who have to prove that a
payment integration works before it goes live.

```
"Verify I cannot refund more than the captured amount"
        │
        ▼
  Claude (tool use) ── record_plan ─▶ create_order ─▶ refund_capture ─▶ refund_capture(expect=error) ─▶ finish
        │                                   │
        │                                   ▼
        │                         PayPal Sandbox REST APIs
        ▼                                   │
  Deterministic validator ◀─────────────────┘   (status codes, money math, error schema, state transitions)
        │
        ▼
  Report: PASS / FAIL / INCONCLUSIVE + findings + PayPal debug IDs  →  Markdown · JSON · JUnit XML · live web UI
```

## What it found

While testing refunds, the agent surfaced sandbox behaviour a merchant could easily get wrong. After refunding
10.00 of a 20.00 capture:

| Refund request | PayPal response | Money actually refunded |
|---|---|---|
| 15.00 | `422 REFUND_AMOUNT_EXCEEDED` ✅ | none |
| **20.00** (the original capture amount) | **`201 COMPLETED`** ❌ | **10.00** |

The over-refund is not rejected; it is silently reduced to the remaining balance. A system that records the
amount it *requested* would book a 20.00 refund the customer never received. The agent rated it CRITICAL and
explained the impact in plain English: [sample report](examples/reports/over-refund-finding.md).
Reproduce it with `python scripts/run_suite.py examples/findings.txt`.

## How it works

| Piece | File | What it does |
|---|---|---|
| PayPal client | `src/payagent/paypal_client.py` | OAuth2 client-credentials (cached token), Orders v2 (create / get / capture / authorize), Payments v2 (captures, authorizations, refunds). It returns errors as data instead of raising, so negative tests work. Supports `PayPal-Mock-Response` negative testing and sends a `PayPal-Request-Id` on every call. |
| AI agent | `src/payagent/agent.py` | Claude tool-use loop. It turns the goal into a plan, calls the API tools with IDs chained from earlier responses, always adds a negative test, writes goal-specific assertions, and explains the findings. Its prompt carries sandbox facts verified against the live API (card orders are charged at create, the 115% over-capture rule, real issue codes). |
| Tools | `src/payagent/tools.py` | The tool schemas Claude sees and the executor that runs them. Each API call becomes a numbered step (`S1`, `S2`, …). |
| Validator | `src/payagent/validator.py` | **The AI decides what to test; code decides pass/fail.** Built-in rules check every step: 2xx, amounts match, capture/refund status, and the PayPal error schema plus `issue` code for `expect="error"` steps. The agent adds its own checks through `assert_field` (JSON path + operator). |
| Report | `src/payagent/report.py` | Markdown, JSON and JUnit XML in `reports/`. Card numbers are masked. |
| Fake PayPal | `src/payagent/fake_paypal.py` | An in-memory stand-in for tests and offline demos (`--fake`), aligned with behaviour observed on the real sandbox. |
| CLI / Web | `cli.py`, `web.py`, `static/index.html` | `payagent "<goal>"` (exit code 0/1/2 for CI) and a web UI that streams the run live. |

**Keeping the AI honest.** An LLM that writes its own assertions can also write wrong ones. So:
- an assertion on a field that isn't in the response is returned to the agent as an error to fix, and nothing is recorded;
- the agent may **retract** one of its own failed assertions only with a stated reason, and the retraction is
  shown in every report (Markdown, web UI, and JUnit as `skipped`);
- built-in checks can never be retracted, so a real API failure can't be explained away.

### AI tools used
- **Claude** with tool use and adaptive thinking is the planning and reasoning engine. It turns English into API
  sequences and explains failures. The demo runs **Claude Haiku 5.5** through the Experiential Labs gateway
  (Anthropic Messages API); any Claude model works by changing `ANTHROPIC_MODEL`.
- **Claude Code** was used to scaffold and develop this repository.

## Setup

Prerequisites: Python 3.10+, a PayPal developer account, and an Anthropic API key (or an Anthropic-compatible gateway).

1. **PayPal sandbox app**: go to [developer.paypal.com](https://developer.paypal.com) → Apps & Credentials → **Sandbox** →
   Create App (Merchant). Copy the **Client ID** and **Secret**.
2. **LLM key**: [console.anthropic.com](https://console.anthropic.com) → API Keys, or a gateway key (see `.env.example`).
3. Install:

```bash
git clone https://github.com/praveen1210/paypal-ai-test-agent.git
cd paypal-ai-test-agent
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, ANTHROPIC_API_KEY
```

`.env` is gitignored, so never commit real keys. Values in `.env` take priority over variables already set in
your shell. The client refuses to run against PayPal **live** URLs.

## Run

CLI:

```bash
payagent "test a partial refund on a captured order"
payagent "verify I cannot refund more than the captured amount"
payagent "authorize 40 USD, capture 25, then void the rest and check the states"
payagent "simulate a declined card" --effort high
payagent "capture the same order twice must fail" --fake         # offline: no PayPal keys needed
payagent "test a partial refund" --junit test-results/payagent.xml
```

Exit codes: `0` PASS, `1` FAIL, `2` INCONCLUSIVE/setup error. Each run writes
`reports/<timestamp>-<goal>.md | .json | .xml`.

Regression suite (every goal in `examples/goals.txt`, a summary table, and one combined JUnit file):

```bash
python scripts/run_suite.py                       # writes reports/junit-suite.xml
```

Web UI (the plan, each API call and each check stream in live; download the report as Markdown, JSON or JUnit):

```bash
uvicorn payagent.web:app --reload
# open http://127.0.0.1:8000
```

API:
- `GET /api/run/stream?goal=...&fake=false` is a Server-Sent Events stream: `plan`, `step_started`,
  `step_finished`, `check`, `check_retracted`, `agent_note`, then a final `result` (or `error`).
- `POST /api/run {"goal": "...", "fake": false}` returns the full report (JSON, `markdown`, `junit`) in one response.

Tests (offline, no keys):

```bash
pytest
ruff check .
```

## Use it in CI

The agent is a CLI with exit codes and JUnit output, so it drops into any pipeline as a quality gate.

- **GitHub Actions**: [`ci.yml`](.github/workflows/ci.yml) runs lint and the offline tests on every push. Its
  `sandbox-suite` job runs the full AI suite against the PayPal sandbox when started by hand (*Actions → CI →
  Run workflow*), using the repo secrets `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `ANTHROPIC_API_KEY`
  (and optionally the variables `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`).
- **Jenkins**: `sh 'python scripts/run_suite.py --junit reports/junit-suite.xml'` then `junit 'reports/junit-suite.xml'`.
- **Azure DevOps**: run the same script, then `PublishTestResults@2` with `testResultsFormat: JUnit`.

## Sample reports

Real runs against the PayPal sandbox, committed so you can see the output without running anything:
[`examples/reports/`](examples/reports/) (Markdown, JSON and JUnit XML for each).

## Deploy (Render)

`render.yaml` is included. Create a new **Blueprint** on Render pointing to this repo, then set
`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` and `ANTHROPIC_API_KEY` (plus `ANTHROPIC_BASE_URL` if you use a
gateway) in the dashboard.

The public demo is protected: at most `DEMO_MAX_CONCURRENT` runs at once (default 2) and `DEMO_RUNS_PER_IP`
runs per visitor every `DEMO_WINDOW_MINUTES` (default 6 per 10 minutes). Extra requests get HTTP 429 with a
clear message.

## Notes and limits
- Card-funded orders use a sandbox test card (`PAYPAL_TEST_CARD_NUMBER`), so they complete with no buyer clicks.
  In the sandbox, a card order is captured (or authorized) at create time (status `COMPLETED`); the agent
  knows this. If you get `PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING`, your sandbox business account can't take cards:
  create a **United States** sandbox business account and a new app linked to it.
- Any Anthropic Messages-compatible endpoint works: set `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` and
  `ANTHROPIC_MODEL` (see `.env.example` for a gateway example).
- `payment_method="paypal"` orders need a sandbox **buyer** to approve them in the browser. The CLI prints the
  link and waits (`wait_for_buyer_approval`).
- The agent's plan varies between runs (it is an AI), but pass/fail is always decided by deterministic code.
- The fake PayPal models the common rules only. The real sandbox is the source of truth.

## License

[MIT](LICENSE)
