from __future__ import annotations

from wm_agents_validator.models.plugin_result import PluginResult, Violation
from pydantic import BaseModel, Field


class VerificationReport(BaseModel):
    trace_id: str
    contract_id: str
    passed: bool
    overall_score: float
    plugin_results: list[PluginResult] = Field(default_factory=list)
    blocking_checks: dict[str, bool] = Field(default_factory=dict)
    violations: list[Violation] = Field(default_factory=list)
