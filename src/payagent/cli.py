"""Command line entry point.

    payagent "test a partial refund on a captured order"

Exit codes (CI friendly): 0 = PASS, 1 = FAIL, 2 = INCONCLUSIVE / setup error.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from typing import Any

from .config import Settings
from .report import save, to_markdown
from .runner import run_goal

EXIT = {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}


def _print_event(kind: str, data: dict[str, Any]) -> None:
    if kind == "plan":
        print("\nPlan:")
        for i, s in enumerate(data["steps"], 1):
            print(f"  {i}. {s}")
        print()
    elif kind == "step_started":
        print(f"-> {data['step_id']} {data['tool']} {data['args']}")
    elif kind == "step_finished":
        step = data["step"]
        status = step.response.status if step.response else step.error
        ok = sum(c.passed for c in step.checks)
        print(f"   HTTP {status}  checks {ok}/{len(step.checks)}")
        for c in step.checks:
            if not c.passed:
                print(f"   FAIL {c.description}: expected {c.expected!r}, got {c.actual!r}")
    elif kind == "check":
        c = data["check"]
        print(f"   {'PASS' if c.passed else 'FAIL'} [assert] {c.description} (actual={c.actual!r})")
    elif kind == "approval_needed":
        print(f"\n*** Buyer approval needed. Open and approve with a sandbox buyer account:\n    {data['url']}\n")
    elif kind == "agent_note":
        print(f"[agent] {data['text'].strip()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="payagent", description="AI Payment Test Agent for PayPal sandbox.")
    parser.add_argument("goal", help='Plain-English test goal, e.g. "test a partial refund on a captured order"')
    parser.add_argument("--fake", action="store_true", help="Use the in-memory fake PayPal (no sandbox keys).")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="Claude effort level.")
    parser.add_argument("--out", help="Reports directory (default: REPORTS_DIR or ./reports).")
    parser.add_argument("--quiet", action="store_true", help="Only print the final report.")
    args = parser.parse_args(argv)
    # Windows consoles default to cp1252 and crash on the report's emoji.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    settings = Settings.from_env()
    overrides: dict[str, Any] = {}
    if args.fake:
        overrides["use_fake_paypal"] = True
    if args.effort:
        overrides["anthropic_effort"] = args.effort
    if args.out:
        overrides["reports_dir"] = args.out
    settings = dataclasses.replace(settings, **overrides)

    try:
        result = run_goal(args.goal, settings, on_event=None if args.quiet else _print_event)
    except RuntimeError as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return 2

    md_path, json_path = save(result, settings.reports_dir)  # save first so a print error can't lose it
    print("\n" + to_markdown(result))
    print(f"Report saved: {md_path}\nJSON:         {json_path}")
    return EXIT[result.verdict]


if __name__ == "__main__":
    sys.exit(main())
