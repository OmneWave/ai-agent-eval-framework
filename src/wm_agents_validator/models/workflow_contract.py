from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IntentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_skill: str | list[str]
    allowed_skills: list[str] = Field(default_factory=list)


class ToolPolicy(BaseModel):
    required: list[str] = Field(default_factory=list)
    allowed: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class FileSpec(BaseModel):
    path: str
    mutability: Literal["read_only", "tool_managed", "editable"] = "editable"


class ResourceSpec(BaseModel):
    agent: str
    skip_if: str | None = None
    operation: str | None = None
    context: list[str] = Field(default_factory=list)
    tools: ToolPolicy = Field(default_factory=ToolPolicy)
    files: list[FileSpec] = Field(default_factory=list)


class BudgetSpec(BaseModel):
    """Trace-level resource budget. Any field left unset means no limit is enforced."""

    max_duration_ms: int | None = None
    max_total_tokens: int | None = None
    max_cost_usd: float | None = None


class WorkflowContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: str
    contract_version: str
    intent: IntentSpec
    resources: dict[str, ResourceSpec] = Field(default_factory=dict)
    # Paths (glob patterns supported) that are always fine to read via read_files
    # even though no resource declares them as context/target -- e.g. platform
    # catalog/reference docs an agent legitimately consults while exploring.
    # Reading them is never required and never counted as "unrelated" scope creep;
    # not reading them is never penalized either.
    allowed_context_reads: list[str] = Field(default_factory=list)
    blocking_checks: list[str] = Field(default_factory=list)
    slo: dict[str, float] | None = None
    budget: BudgetSpec | None = None

    @property
    def contract_id(self) -> str:
        return f"{self.workflow}@{self.contract_version}"
