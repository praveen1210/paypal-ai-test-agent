"""Plain data records shared by the client, agent, validator and report."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ApiResponse:
    method: str
    path: str
    status: int
    body: Any
    debug_id: str | None = None
    request_body: Any = None
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass
class Check:
    description: str
    passed: bool
    expected: Any = None
    actual: Any = None
    step_id: str | None = None
    source: str = "auto"  # "auto" (built-in rule) or "agent" (assert_field)
    retracted: str | None = None  # agent's reason when it withdrew its own faulty assertion; kept for audit


@dataclass
class Step:
    id: str
    tool: str
    args: dict[str, Any]
    expect: str  # "success" | "error"
    response: ApiResponse | None = None
    error: str | None = None
    checks: list[Check] = field(default_factory=list)


@dataclass
class Finding:
    title: str
    severity: str  # "critical" | "major" | "minor" | "info"
    explanation: str
    step_ids: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    goal: str
    started_at: str
    finished_at: str = ""
    model: str = ""
    steps: list[Step] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    summary: str = ""
    plan: list[str] = field(default_factory=list)
    agent_error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)

    def active_checks(self) -> list[Check]:
        """Checks that count toward the verdict (retracted agent assertions are excluded)."""
        return [c for c in self.checks if not c.retracted]

    @property
    def verdict(self) -> str:
        active = self.active_checks()
        if self.agent_error or not active:
            return "INCONCLUSIVE"
        return "PASS" if all(c.passed for c in active) else "FAIL"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["verdict"] = self.verdict
        return data
