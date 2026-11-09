"""Run every goal in a goals file and print a summary table.

    python scripts/run_suite.py                     # examples/goals.txt against the sandbox
    python scripts/run_suite.py my_goals.txt --fake

Exit code: 0 if every goal PASSes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from pathlib import Path

from payagent.config import Settings
from payagent.report import save, to_junit
from payagent.runner import run_goal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("goals_file", nargs="?", default="examples/goals.txt")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--junit", default="reports/junit-suite.xml", help="Combined JUnit XML for CI.")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    settings = Settings.from_env()
    if args.fake:
        settings = dataclasses.replace(settings, use_fake_paypal=True)
    goals = [g.strip() for g in Path(args.goals_file).read_text(encoding="utf-8").splitlines()
             if g.strip() and not g.startswith("#")]

    rows, results = [], []
    for i, goal in enumerate(goals, 1):
        print(f"[{i}/{len(goals)}] {goal}", flush=True)
        started = time.time()
        result = run_goal(goal, settings)
        results.append(result)
        md_path, _ = save(result, settings.reports_dir)
        active = result.active_checks()
        passed = sum(c.passed for c in active)
        rows.append((result.verdict, f"{passed}/{len(active)}", len(result.steps),
                     f"{time.time() - started:.0f}s", goal, md_path.name, result.agent_error or ""))
        print(f"    {rows[-1][0]} {rows[-1][1]} checks, {rows[-1][2]} steps, {rows[-1][3]}"
              + (f"  ERROR: {result.agent_error}" if result.agent_error else ""), flush=True)

    print("\n| Verdict | Checks | Steps | Time | Goal | Report |\n|---|---|---|---|---|---|")
    for v, c, s, t, g, r, _ in rows:
        print(f"| {v} | {c} | {s} | {t} | {g} | {r} |")
    Path(args.junit).parent.mkdir(parents=True, exist_ok=True)
    Path(args.junit).write_text(to_junit(results), encoding="utf-8")
    print(f"\nJUnit XML: {args.junit}")
    return 0 if all(r[0] == "PASS" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
