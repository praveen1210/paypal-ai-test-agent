"""Report generation: Markdown (human), JSON (machine), JUnit XML (Jenkins / Azure DevOps / GitHub CI)."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .models import RunResult

_ICON = {"PASS": "✅", "FAIL": "❌", "INCONCLUSIVE": "⚠️"}


def _cell(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 80 else text[:77] + "..."


def to_markdown(result: RunResult) -> str:
    active = result.active_checks()
    passed = sum(c.passed for c in active)
    retracted = len(result.checks) - len(active)
    lines = [
        f"# {_ICON[result.verdict]} {result.verdict}: {result.goal}",
        "",
        f"- **Checks:** {passed}/{len(active)} passed" + (f" ({retracted} retracted by the agent)" if retracted else ""),
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
        live = [c for c in s.checks if not c.retracted]
        ok = sum(c.passed for c in live)
        lines.append(f"| {s.id} | {call} | {s.expect} | {r.status if r else 'ERR'} | "
                     f"{(r.debug_id or '') if r else ''} | {ok}/{len(live)} |")

    lines += ["", "## Checks", "", "| | Step | Check | Expected | Actual | Source |", "|---|---|---|---|---|---|"]
    for c in result.checks:
        icon = "↩️" if c.retracted else ("✅" if c.passed else "❌")
        source = f"agent, retracted: {_cell(c.retracted)}" if c.retracted else c.source
        lines.append(f"| {icon} | {c.step_id or ''} | {_cell(c.description)} | "
                     f"{_cell(c.expected)} | {_cell(c.actual)} | {source} |")
    return "\n".join(lines) + "\n"


def _seconds(result: RunResult) -> float:
    try:
        return (datetime.fromisoformat(result.finished_at) - datetime.fromisoformat(result.started_at)).total_seconds()
    except ValueError:
        return 0.0


def _testsuite(result: RunResult) -> ET.Element:
    """One <testsuite> per goal; one <testcase> per check (auto and agent assertions)."""
    failures = sum(not c.passed for c in result.active_checks())
    skipped = len(result.checks) - len(result.active_checks())
    errors = 1 if result.agent_error else 0
    suite = ET.Element("testsuite", {
        "name": result.goal, "tests": str(len(result.checks) + errors), "failures": str(failures),
        "errors": str(errors), "skipped": str(skipped), "timestamp": result.started_at, "time": f"{_seconds(result):.1f}",
    })
    props = ET.SubElement(suite, "properties")
    for name, value in (("verdict", result.verdict), ("model", result.model), ("api_steps", str(len(result.steps)))):
        ET.SubElement(props, "property", {"name": name, "value": value})
    tools = {s.id: s.tool for s in result.steps}
    for c in result.checks:
        case = ET.SubElement(suite, "testcase", {
            "classname": f"payagent.{tools.get(c.step_id or '', 'agent')}",
            "name": f"{c.step_id or '-'}: {c.description}",
        })
        if c.retracted:
            ET.SubElement(case, "skipped", {"message": f"retracted by agent: {c.retracted}"})
        elif not c.passed:
            failure = ET.SubElement(case, "failure", {
                "type": "AssertionError",
                "message": f"expected {json.dumps(c.expected, default=str)}, got {json.dumps(c.actual, default=str)}",
            })
            failure.text = f"step={c.step_id} source={c.source}"
    if result.agent_error:
        case = ET.SubElement(suite, "testcase", {"classname": "payagent.agent", "name": "agent run completed"})
        ET.SubElement(case, "error", {"type": "AgentError", "message": result.agent_error})
    out = [result.summary] + [f"[{f.severity.upper()}] {f.title}: {f.explanation}" for f in result.findings]
    ET.SubElement(suite, "system-out").text = "\n\n".join(o for o in out if o)
    return suite


def to_junit(results: RunResult | Iterable[RunResult]) -> str:
    """JUnit XML for one run or many (a suite)."""
    runs = [results] if isinstance(results, RunResult) else list(results)
    root = ET.Element("testsuites", {"name": "payagent"})
    for r in runs:
        root.append(_testsuite(r))
    for attr in ("tests", "failures", "errors"):
        root.set(attr, str(sum(int(s.get(attr, "0")) for s in root)))
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def save(result: RunResult, directory: str | Path) -> tuple[Path, Path]:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", result.goal.lower()).strip("-")[:50] or "run"
    stamp = result.started_at.replace(":", "").replace("-", "").replace("+0000", "Z")[:15]
    md_path = out / f"{stamp}-{slug}.md"
    json_path = md_path.with_suffix(".json")
    md_path.write_text(to_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
    md_path.with_suffix(".xml").write_text(to_junit(result), encoding="utf-8")
    return md_path, json_path
