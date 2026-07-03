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
    plugin: str
    passed: bool
    score: float
    violations: list[Violation] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    blocking_checks: dict[str, bool] = Field(default_factory=dict)
