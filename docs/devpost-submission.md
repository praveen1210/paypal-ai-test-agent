# Devpost submission draft: copy each section into the matching Devpost field

---

## Project name

AI Payment Test Agent

## Elevator pitch (Devpost limit: 200 characters)

Describe a payment test in plain English. An AI agent runs it against the PayPal sandbox, verifies every response, and explains bugs. It already found one.

---

## About the project (main description, Markdown is supported)

### Inspiration

I'm an automation test engineer. Payment integrations are where bugs cost real money, and they are also the slowest
thing to test: every refund, capture, void and decline path needs its own carefully scripted API test. Most teams test
the happy path and hope. I wanted a tester that takes a sentence like *"test a partial refund on a captured order"* and
does the rest, the way I would, but in seconds.

### What it does

You type a test goal in plain English. The agent:

1. **Plans** the test: setup steps, the actual checks, and at least one *negative* test it adds on its own (e.g. "refund more than what remains").
2. **Runs it live** against the PayPal sandbox: Orders v2 (create, capture, authorize) and Payments v2 (captures, authorizations, refunds, voids), chaining real IDs from one response to the next.
3. **Validates every response** with deterministic code: status codes, money math, state transitions (`COMPLETED → PARTIALLY_REFUNDED → REFUNDED`), and PayPal's error schema and issue codes for negative tests.
4. **Reports** a PASS / FAIL verdict with plain-English findings, the business impact, and each step's PayPal debug ID, as Markdown, JSON and **JUnit XML**, so it plugs straight into Jenkins, Azure DevOps or GitHub Actions as a quality gate.

The web app streams the plan, every API call and every check live while the agent works. There's also a CLI with CI exit codes and a regression suite.

**It found a real issue.** After refunding $10 of a $20 capture:

| Refund request | PayPal sandbox response | Actually refunded |
|---|---|---|
| $15 | `422 REFUND_AMOUNT_EXCEEDED` (correct) | nothing |
| **$20** (the original capture amount) | **`201 COMPLETED`** | **$10** |

The over-refund isn't rejected; it's silently reduced to the remaining balance. A merchant system that records the
amount it *requested* would book a $20 refund the customer never received. The agent flagged it as CRITICAL and explained
why it matters. I reproduced it on every run since, and it's in the repo as a one-command reproduction.

### How I built it

- **Python + FastAPI** backend; a single-page UI that consumes a **Server-Sent Events** stream for live progress.
- **PayPal sandbox REST APIs** via a small client with OAuth2 token caching, `PayPal-Request-Id` on every call, and
  `PayPal-Mock-Response` for simulating processor declines. Errors are returned as data, not exceptions, so negative
  tests are first-class.
- **Claude (Anthropic Messages API, tool use)** as the agent. It gets one tool per PayPal operation plus `record_plan`,
  `assert_field`, `retract_assertion` and `finish`.
- **The core design rule: the AI decides *what* to test; code decides *pass or fail*.** A deterministic validator
  applies built-in checks to every step, and the agent's own assertions are JSON-path checks evaluated by code.
- **Keeping the AI honest:** an assertion on a field that doesn't exist is sent back to the agent to fix instead of being
  recorded; the agent may retract only *its own* assertions, with a reason that shows up in every report; built-in checks
  can never be retracted.
- **Deployed on Render** from a Blueprint (`render.yaml`): auto-deploy on every push, health checks, and demo
  safeguards (concurrency cap and per-visitor rate limit, since every run makes real sandbox and LLM calls).
- **GitHub Actions CI** runs lint and 20 offline tests on every push, using an in-memory fake PayPal aligned with
  behaviour observed on the real sandbox. A manual workflow runs the live AI suite against the sandbox and uploads the
  reports and JUnit results as build artifacts.

### Challenges I ran into

- **Card payments were rejected** (`PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING`) until I moved to a US sandbox business account.
- **Sandbox behaviour differs from what you'd assume:** card orders are captured at creation, authorizations can be
  captured up to 115% of the authorized amount, and mock responses on the authorization-capture endpoint return a bare
  403. I verified each against the live API and taught the agent these facts, enforcing the last one in the tool schema
  rather than just the prompt.
- **LLMs write wrong assertions sometimes.** Early runs showed false FAILs from guessed field paths and guessed error
  codes. That led to the "code decides pass/fail" architecture and the audited retraction mechanism.

### Accomplishments I'm proud of

- It found a genuine, reproducible behaviour that matters to merchants, without being told where to look.
- All 8 goals in the regression suite pass against the live sandbox in a single run (168 of 168 checks), and every
  verdict is explainable and auditable.
- It's a complete product, not a notebook: web UI, CLI, CI integration, JUnit output, a hosted demo and sample reports.

### What I learned

The AI is great at deciding what is worth testing and at explaining failures to humans; it should never be the
one deciding whether a test passed. Separating those two jobs made the tool trustworthy.

### What's next

- Point the agent at a **merchant's own backend** (not just PayPal directly) to test real integrations end to end.
- More PayPal surfaces: subscriptions, disputes, webhooks (signature verification), Vault.
- **Export a successful agent run as a fixed regression test** (pytest / Rest Assured), so AI exploration turns into stable CI tests.
- Browser automation (Playwright) for buyer-approval flows with sandbox buyer accounts.

---

## Built with (Devpost tags)

python, fastapi, paypal, paypal-orders-api, paypal-payments-api, claude, anthropic, ai-agents, render, github-actions, server-sent-events, junit, httpx, pytest

## "Try it out" links

- Live demo: https://paypal-ai-test-agent.onrender.com
- Code (MIT): https://github.com/praveen1210/paypal-ai-test-agent

## Video demo link

https://youtu.be/iqjfE30s5RQ

---

## Tools field: which AI tools were used and how

- **Claude Haiku 5.5 (Anthropic Messages API with tool use), accessed through the Experiential Labs gateway.** This is
  the agent at runtime. It turns the plain-English goal into a test plan, chooses and sequences the PayPal API calls
  (passing real IDs between steps), writes goal-specific assertions, and writes the plain-English findings and business
  impact. Pass/fail is not decided by the model: a deterministic validator evaluates every check. Any Claude model can be
  used by changing one setting.
- **Claude Code** was used as a development assistant to scaffold, implement and test the codebase.
- **Microsoft Edge neural text-to-speech (via edge-tts)** generated the voiceover in the demo video.

---

## Prizes to mention or opt into (if the form asks)

- Best Use of PayPal + AI
- Most Impactful
- Best Demo Delivery
- Best Use of Render (deployed on Render via Blueprint)

---

## Final checklist before you click Submit

- [x] YouTube video uploaded: https://youtu.be/iqjfE30s5RQ (double-check Visibility = **Public**, not Unlisted)
- [ ] Repo is public, and the MIT license shows in the GitHub "About" section
- [ ] Live demo opens (wake it up a minute before submitting; the free plan sleeps)
- [ ] Render `DEMO_RUNS_PER_IP` is back to `6`
- [ ] Submitted before **Nov 12, 12:00 PM PT = Nov 13, 1:30 AM IST**
