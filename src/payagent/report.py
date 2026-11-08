"""Report generation: Markdown (human) + JSON (machine / CI)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import RunResult

_ICON = {"PASS": "✅", "FAIL": "❌", "INCONCLUSIVE": "⚠️"}


def _cell(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 80 else text[:77] + "..."


def to_markdown(result: RunResult) -> str:
    passed = sum(c.passed for c in result.checks)
    lines = [
        f"# {_ICON[result.verdict]} {result.verdict}: {result.goal}",
        "",
        f"- **Checks:** {passed}/{len(result.checks)} passed",
        f"- **API steps:** {len(result.steps)}",
        f"- **Model:** {result.model}",
        f"- **Run:** {result.started_at} → {result.finished_at}",
    ]
    if result.agent_error:
        lines += ["", f"> **Agent error:** {result.agent_error}"]
    lines += ["", "## Summary", "", result.summary or "_No summary._"]

    if result.findings:
        lines += ["", "## Findings", ""]
        for f in result.findings:
            refs = f" (steps: {', '.join(f.step_ids)})" if f.step_ids else ""
            lines += [f"### [{f.severity.upper()}] {f.title}{refs}", "", f.explanation, ""]

    if result.plan:
        lines += ["", "## Test plan", ""] + [f"{i}. {s}" for i, s in enumerate(result.plan, 1)]

    lines += ["", "## Steps", "", "| Step | Call | Expect | HTTP | Debug ID | Checks |", "|---|---|---|---|---|---|"]
    for s in result.steps:
        r = s.response
        call = f"`{r.method} {r.path}`" if r else s.tool
        ok = sum(c.passed for c in s.checks)
        lines.append(f"| {s.id} | {call} | {s.expect} | {r.status if r else 'ERR'} | "
                     f"{(r.debug_id or '') if r else ''} | {ok}/{len(s.checks)} |")

    lines += ["", "## Checks", "", "| | Step | Check | Expected | Actual | Source |", "|---|---|---|---|---|---|"]
    for c in result.checks:
        lines.append(f"| {'✅' if c.passed else '❌'} | {c.step_id or ''} | {_cell(c.description)} | "
                     f"{_cell(c.expected)} | {_cell(c.actual)} | {c.source} |")
    return "\n".join(lines) + "\n"


def save(result: RunResult, directory: str | Path) -> tuple[Path, Path]:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", result.goal.lower()).strip("-")[:50] or "run"
    stamp = result.started_at.replace(":", "").replace("-", "").replace("+0000", "Z")[:15]
    md_path = out / f"{stamp}-{slug}.md"
    json_path = md_path.with_suffix(".json")
    md_path.write_text(to_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
    return md_path, json_path
