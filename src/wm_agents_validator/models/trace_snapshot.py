from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

DELEGATION_TOOL_NAMES = frozenset(
    {
        "start_new_conversation_with_agent",
        "continue_conversation_with_agent",
    }
)
FILE_WRITE_TOOLS = frozenset({"write_file", "edit_file_content", "delete_file"})
SKILL_TOOL = "load_skill"


class SkillLoadRecord(BaseModel):
    skill_names: list[str]
    success: bool = True
    timestamp: str | None = None
    agent_id: str | None = None
    error_message: str | None = None


class DelegationRecord(BaseModel):
    parent_agent: str
    child_agent: str
    tool_name: str = "continue_conversation_with_agent"
    timestamp: str | None = None


class FileChangeRecord(BaseModel):
    path: str
    operation: Literal["read", "write", "edit", "delete"] = "write"
    tool_name: str | None = None


class ErrorRecord(BaseModel):
    name: str
    message: str | None = None
    type: str | None = None
    timestamp: str | None = None


class EventRecord(BaseModel):
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None


class SpanRecord(BaseModel):
    id: str
    name: str
    type: Literal[
        "SPAN",
        "TOOL",
        "EVENT",
        "GENERATION",
        "AGENT_RUN",
        "AGENT",
        "CHAIN",
        "RETRIEVER",
        "EVALUATOR",
        "EMBEDDING",
        "GUARDRAIL",
    ]
    parent_id: str | None = None
    agent_id: str | None = None
    timestamp: str | None = None
    end_time: str | None = None
    level: str | None = None
    input: dict[str, Any] | None = None
    output: Any | None = None
    success: bool | None = None
    error_message: str | None = None


class FailedToolRecord(BaseModel):
    name: str
    error_message: str | None = None
    timestamp: str | None = None
    span_id: str | None = None


class ToolsSummary(BaseModel):
    called: list[str] = Field(default_factory=list)
    failed: list[FailedToolRecord] = Field(default_factory=list)


class TraceSnapshot(BaseModel):
    trace_id: str
    session_id: str | None = None
    run_id: str | None = None
    entry_agent: str | None = None
    status: Literal["success", "error", "unknown"] = "unknown"
    duration_ms: int | None = None
    user_prompt: str | None = None
    final_response: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    custom_events: list[EventRecord] = Field(default_factory=list)
    skill_loads: list[SkillLoadRecord] = Field(default_factory=list)
    tools_summary: ToolsSummary = Field(default_factory=ToolsSummary)
    spans: list[SpanRecord] = Field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return list(self.tools_summary.called)

    @property
    def errors(self) -> list[ErrorRecord]:
        records: list[ErrorRecord] = []
        for span in self.spans:
            if span.level and span.level.upper() == "ERROR":
                records.append(
                    ErrorRecord(
                        name=span.name,
                        message=span.error_message,
                        type=span.type,
                        timestamp=span.timestamp,
                    )
                )
            elif span.type == "TOOL" and span.success is False:
                records.append(
                    ErrorRecord(
                        name=_span_base_name(span.name),
                        message=span.error_message,
                        type="TOOL",
                        timestamp=span.timestamp,
                    )
                )
        return records

    @property
    def delegations(self) -> list[DelegationRecord]:
        records: list[DelegationRecord] = []
        for span in self.spans:
            if span.type != "TOOL":
                continue
            base_name = _span_base_name(span.name)
            if base_name not in DELEGATION_TOOL_NAMES:
                continue
            child_agent = _delegation_target(span)
            if not child_agent:
                continue
            parent_agent = span.agent_id or self.entry_agent or "unknown"
            records.append(
                DelegationRecord(
                    parent_agent=parent_agent,
                    child_agent=child_agent,
                    tool_name=base_name,
                    timestamp=span.timestamp,
                )
            )
        return records

    @property
    def file_changes(self) -> list[FileChangeRecord]:
        changes: list[FileChangeRecord] = []
        for span in self.spans:
            if span.type != "TOOL":
                continue
            base_name = _span_base_name(span.name)
            if base_name not in FILE_WRITE_TOOLS:
                continue
            operation = "delete" if "delete" in base_name else "edit" if "edit" in base_name else "write"
            for path in _extract_paths_from_input(span.input or {}):
                changes.append(
                    FileChangeRecord(path=path, operation=operation, tool_name=base_name)
                )
        return changes

    @property
    def agents_in_trace(self) -> set[str]:
        agents: set[str] = set()
        if self.entry_agent:
            agents.add(self.entry_agent)
        for span in self.spans:
            if span.agent_id:
                agents.add(span.agent_id)
            child = _delegation_target(span)
            if child:
                agents.add(child)
        return agents


def _span_base_name(name: str) -> str:
    return name.split(" (")[0].strip() if name else name


def _delegation_target(span: SpanRecord) -> str | None:
    if span.type != "TOOL":
        return None
    base_name = _span_base_name(span.name)
    if base_name not in DELEGATION_TOOL_NAMES:
        return None
    tool_input = span.input or {}
    target = tool_input.get("target_agent") or tool_input.get("agent")
    return str(target) if target else None


def _extract_paths_from_input(tool_input: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("path", "file_path", "file"):
        value = tool_input.get(key)
        if value:
            paths.append(str(value))
    files = tool_input.get("paths") or tool_input.get("files") or []
    if isinstance(files, list):
        paths.extend(str(path) for path in files)
    change = tool_input.get("change")
    if isinstance(change, str):
        match = re.search(r"([\w./-]+\.(?:html|json|js|css|xml))", change)
        if match:
            paths.append(match.group(1))
    return paths
