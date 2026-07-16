from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from wm_agents_validator.contracts.expressions import glob_match

DELEGATION_TOOL_NAMES = frozenset(
    {
        "start_new_conversation_with_agent",
        "continue_conversation_with_agent",
    }
)
FILE_WRITE_TOOLS = frozenset({"write_file", "edit_file_content", "delete_file"})
VARIABLE_CREATE_TOOLS = frozenset({"ui_createApiAwareVariable", "ui_createNonApiAwareVariable", "ui_updateVariable"})
"""Platform tools that create/update a page's variable definition directly --
confirmed (via a real trace, not the earlier speculative stand-in) to sometimes
carry NO accompanying write_file/edit_file_content call on the underlying
`.variables.json` at all. See ``file_changes``'s handling of these tools below,
and docs/CONTRACT_SPEC.md's former "known limitation" note (now resolved)."""
SKILL_TOOL = "load_skill"
EXECUTE_TOOL_WRAPPER = "execute_tool"
"""wm-agent-server's generic dispatcher tool (`execute_tool(tool_name, tool_args)`,
see src/tools.py) -- the trace records the span as `execute_tool`, but the tool
policy (`tools.required`/`forbidden`) is written in terms of the *actual* tool
name passed as its `tool_name` argument. See `_build_tools_summary`."""


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


class GenerationRecord(BaseModel):
    """A single LLM call (Langfuse GENERATION observation) with its usage/cost."""

    name: str | None = None
    agent_id: str | None = None
    timestamp: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


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
    generations: list[GenerationRecord] = Field(default_factory=list)
    trace_total_cost_usd: float | None = None
    """Langfuse's own pre-aggregated ``totalCost`` for the trace, used as a
    fallback when per-generation cost data wasn't available/fetched."""

    @property
    def tool_names(self) -> list[str]:
        return list(self.tools_summary.called)

    @property
    def total_tokens(self) -> int | None:
        values = [g.total_tokens for g in self.generations if g.total_tokens is not None]
        return sum(values) if values else None

    @property
    def total_cost_usd(self) -> float | None:
        values = [g.cost_usd for g in self.generations if g.cost_usd is not None]
        if values:
            return sum(values)
        return self.trace_total_cost_usd

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
            for path in extract_paths_from_input(span.input or {}, base_name):
                changes.append(
                    FileChangeRecord(path=path, operation=operation, tool_name=base_name)
                )
        for span in self.spans:
            if span.type != "TOOL":
                continue
            base_name = _span_base_name(span.name)
            if base_name not in VARIABLE_CREATE_TOOLS:
                continue
            path = _variable_change_path(span.input or {})
            if path is None:
                continue
            operation = "edit" if base_name == "ui_updateVariable" else "write"
            changes.append(FileChangeRecord(path=path, operation=operation, tool_name=base_name))
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


# Path-bearing argument name(s) per tool, taken directly from each tool's
# @tool-decorated signature in wm-agent-server's src/tools.py, so path
# extraction matches the real schema instead of guessing at key names.
# MCP-provided tools (invoked via execute_tool's tool_args) aren't defined in
# that repo and aren't listed here; they fall back to the generic heuristic.
_TOOL_PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "read_files": ("file_paths",),  # list[str]
    "write_file": ("file_path",),
    "edit_file_content": ("file_path",),
    "delete_file": ("file_path",),
    "get_file_diagnostics": ("file_path",),
    "get_file_patch_for_checkpoints": ("file_path",),
    "find_files_by_glob": ("folder_path",),
    "grep_in_files": ("path",),
    "vcs_file_updated": ("file_path",),
}


def extract_paths_from_input(tool_input: dict[str, Any], tool_name: str | None = None) -> list[str]:
    if tool_name in VARIABLE_CREATE_TOOLS:
        # These calls often carry only `pageName` (no path/file_path key at all --
        # confirmed via a real trace), which neither _TOOL_PATH_FIELDS nor the
        # generic fallback below know how to read. Route through the same
        # path-resolution `file_changes` uses, so every consumer of this
        # function (input_context's/output's evidencing-span lookups included)
        # agrees on what path a variable-creation call touched.
        variable_path = _variable_change_path(tool_input)
        if variable_path:
            return [variable_path]

    fields = _TOOL_PATH_FIELDS.get(tool_name) if tool_name else None
    if fields:
        paths: list[str] = []
        for key in fields:
            value = tool_input.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                paths.extend(str(v) for v in value)
            else:
                paths.append(str(value))
        if paths:
            return paths

    # Fallback heuristic for tools with no known schema entry above (e.g.
    # MCP/platform tools reached through execute_tool, or unrecognized names).
    paths = []
    for key in ("path", "file_path", "file"):
        value = tool_input.get(key)
        if value:
            paths.append(str(value))
    files = (
        tool_input.get("paths")
        or tool_input.get("files")
        or tool_input.get("file_paths")
        or tool_input.get("folder_path")
        or []
    )
    if isinstance(files, list):
        paths.extend(str(path) for path in files)
    elif files:
        paths.append(str(files))
    change = tool_input.get("change")
    if isinstance(change, str):
        match = re.search(r"([\w./-]+\.(?:html|json|js|css|xml))", change)
        if match:
            paths.append(match.group(1))
    return paths


def _variable_change_path(tool_input: dict[str, Any]) -> str | None:
    """The ``.variables.json`` path a ``VARIABLE_CREATE_TOOLS`` call targets --
    field shape isn't consistent across observed calls: a real trace carries
    ``pageName`` directly (convention-derive the path from it), while this
    repo's own fixture instead carries a ``path``/``file_path`` pointing at the
    file already. Accept either rather than betting on one.
    """
    page = tool_input.get("pageName")
    if page:
        return f"src/main/webapp/pages/{page}/{page}.variables.json"
    path = tool_input.get("path") or tool_input.get("file_path")
    return str(path) if path else None


def _paths_match(pattern: str, path: str) -> bool:
    """Compare a resolved resource path against an actually-referenced path, ignoring
    a leading '/' on either side. Tools sometimes report the same underlying file as
    project-relative ('services/...') and sometimes as absolute-looking
    ('/services/...'), so a leading slash on either side must never by itself cause a
    false negative. Shared by ``input_context.py`` (context-retrieval checks) and
    ``output.py`` (``match`` clause evidence-span lookup).
    """
    norm_pattern = pattern.lstrip("/")
    norm_path = path.lstrip("/")
    return norm_path == norm_pattern or glob_match(norm_pattern, norm_path)
