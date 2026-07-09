from __future__ import annotations

from pydantic import BaseModel, Field


class Violation(BaseModel):
    code: str
    message: str
    plugin: str | None = None
    resource: str | None = None
    evidence: dict = Field(default_factory=dict)


class EvalContext(BaseModel):
    """Runtime bindings for skip_if and path template resolution."""

    bindings: dict = Field(default_factory=dict)
    task: dict = Field(default_factory=dict)


class PluginResult(BaseModel):
    """``violations`` only ever reflects what went *wrong*; a plugin that
    checks several named things (e.g. one entry per contract resource, or one
    per budgeted metric) and wants that full breakdown surfaced -- including
    the things that passed -- should additionally populate a standard
    ``evidence["checks"]`` map:

        evidence["checks"] = {
            "<label>": {"passed": bool, "detail": "<human-readable reason>"},
            ...
        }

    Renderers (console, HTML) read this generic shape to show "what was
    validated" regardless of pass/fail, without needing to know anything
    plugin-specific about the rest of ``evidence``.
    """

    plugin: str
    passed: bool
    score: float
    violations: list[Violation] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)


def score_from_checks(checks: dict[str, dict]) -> tuple[bool, float]:
    """Derive (passed, score) from an ``evidence["checks"]`` map.

    Modeled on SWE-bench-style binary resolution: every declared check must hold for
    ``passed`` -- no partial credit, no hard/soft split. ``score`` is the pass ratio over
    the same map, kept only as diagnostic detail (never used to decide ``passed`` or to
    rank/compare models -- see the Scoring section of the contract schema).
    """
    if not checks:
        return True, 1.0
    passed_count = sum(1 for c in checks.values() if c.get("passed"))
    total = len(checks)
    return passed_count == total, passed_count / total
