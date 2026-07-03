from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IntentSpec(BaseModel):
    expected_skill: str


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


class WorkflowContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: str
    contract_version: str
    intent: IntentSpec
    required_metadata: list[str] = Field(default_factory=list)
    resources: dict[str, ResourceSpec] = Field(default_factory=dict)
    blocking_checks: list[str] = Field(default_factory=list)
    slo: dict[str, float] | None = None

    @property
    def contract_id(self) -> str:
        return f"{self.workflow}@{self.contract_version}"
