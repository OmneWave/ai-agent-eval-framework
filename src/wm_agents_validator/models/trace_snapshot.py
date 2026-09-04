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


def unwrap_execute_tool(base_name: str, tool_input: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Resolve a span to the tool it actually invoked and that tool's own
    arguments -- if ``base_name`` is the generic ``execute_tool`` dispatcher,
    return its wrapped ``tool_name``/``tool_args`` instead of the wrapper
    shell, so every name- and path-based check downstream (file-change
    detection, output-evidencing, tool-name policy) sees the real call. Falls
    through unchanged for a direct call, and for a dispatcher call that's
    missing a usable ``tool_name`` (nothing to unwrap to)."""
    if base_name == EXECUTE_TOOL_WRAPPER:
        wrapped_name = tool_input.get("tool_name")
        if wrapped_name:
            return str(wrapped_name), (tool_input.get("tool_args") or {})
    return base_name, tool_input


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
        """A call that *attempted* a write/edit/delete but failed
        (``span.success is False``) never actually changed anything, so it's
        excluded here -- otherwise a failed ``write_file`` call would still
        register as a real change, making ``OutputPlugin`` credit a
        declared write that never happened, or flag the same path as
        "unrelated"/out-of-scope for a change that was never real to begin
        with. ``None``/unset stays permissive (not every tool sets
        ``success`` explicitly), matching ``InputContextPlugin._check_paths``'s
        same convention.
        """
        changes: list[FileChangeRecord] = []
        for span in self.spans:
            if span.type != "TOOL" or span.success is False:
                continue
            base_name, tool_input = unwrap_execute_tool(_span_base_name(span.name), span.input or {})
            if base_name not in FILE_WRITE_TOOLS:
                continue
            operation = "delete" if "delete" in base_name else "edit" if "edit" in base_name else "write"
            for path in extract_paths_from_input(tool_input, base_name):
                changes.append(
                    FileChangeRecord(path=path, operation=operation, tool_name=base_name)
                )
        for span in self.spans:
            if span.type != "TOOL" or span.success is False:
                continue
            base_name, tool_input = unwrap_execute_tool(_span_base_name(span.name), span.input or {})
            if base_name not in VARIABLE_CREATE_TOOLS:
                continue
            path = _variable_change_path(tool_input)
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


def _coerce_path(value: Any) -> str:
    """A path-bearing list item is normally a plain string, but some tool schema
    variants (e.g. ``read_files`` with a per-file ``limit``) wrap it in an object
    like ``{"path": ..., "limit": 60}`` -- pull the real path out instead of
    stringifying the whole object, which would otherwise silently corrupt every
    path-based check (input_context retrieval, unrelated-reads, etc.)."""
    if isinstance(value, dict):
        return str(value.get("path") or value.get("file_path") or value)
    return str(value)


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
                paths.extend(_coerce_path(v) for v in value)
            else:
                paths.append(_coerce_path(value))
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
        paths.extend(_coerce_path(path) for path in files)
    elif files:
        paths.append(_coerce_path(files))
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


def match_satisfied(match: list[Any], tool_input: dict[str, Any]) -> bool:
    """Checks every clause in a ``WriteSpec.match``/``ToolCheck.match`` list
    against one tool call's structured input -- ALL clauses must hold (AND).
    Purely a fold over polymorphic ``clause.satisfied()`` calls -- this
    function has no knowledge of what kinds of clause exist; that logic lives
    entirely on each ``MatchClause`` subclass in ``models/workflow_contract.py``
    (``ExactMatchClause``/``SubstringMatchClause``/``RegexMatchClause``).
    """
    return all(clause.satisfied(tool_input) for clause in match)


def resolve_dotted_tool_calls(spans: list[SpanRecord], dotted_tool: str) -> list[dict[str, Any]]:
    """Resolve a contract-authored ``tool:`` reference -- a plain tool name, or
    a dot-separated chain (e.g. ``execute_tool.ui_applyChangesOnPageMarkup``)
    describing a wrapper call and what it invoked -- to the list of resolved
    innermost-call inputs among ``spans`` that match the *entire* chain.

    This is a purely structural traversal with no built-in knowledge of any
    specific tool's name (``execute_tool`` included): each segment after the
    first is matched by descending into the current input's own
    ``tool_name``/``tool_args`` pair (the shape a generic dispatcher call
    takes) and checking whether ``tool_name`` equals that segment -- the same
    descent applies uniformly regardless of what the outer or inner tool is
    called. A contract that writes a two-segment ``tool:`` for some other
    dispatcher-shaped tool gets the identical traversal for free; nothing here
    is specific to any one tool.

    A one-segment reference (no dots) matches the span directly, with no
    descent at all.

    A call that *attempted* the match but failed (``span.success is False``)
    is excluded -- seeing the right arguments in a call that then errored out
    isn't evidence the change/action actually happened, the same reasoning
    ``TraceSnapshot.file_changes`` and ``InputContextPlugin._check_paths``
    apply to path-based evidence. ``None``/unset stays permissive.
    """
    segments = dotted_tool.split(".")
    resolved: list[dict[str, Any]] = []
    for span in spans:
        if span.type != "TOOL" or span.success is False:
            continue
        if _span_base_name(span.name) != segments[0]:
            continue
        current: Any = span.input or {}
        matched = True
        for segment in segments[1:]:
            if not isinstance(current, dict) or current.get("tool_name") != segment:
                matched = False
                break
            current = current.get("tool_args") or {}
        if matched and isinstance(current, dict):
            resolved.append(current)
    return resolved


def matching_tool_calls(spans: list[SpanRecord], tool_checks: list[Any]) -> list[dict[str, Any]]:
    """Every resolved call satisfying one of the given ``ToolCheck``
    declarations (duck-typed on ``.tool``/``.match``) -- the tool call itself
    is deemed sufficient evidence, without extracting or comparing a file
    path at all. See ``ToolCheck`` in ``models/workflow_contract.py`` and
    ``resolve_dotted_tool_calls`` above.
    """
    calls: list[dict[str, Any]] = []
    for check in tool_checks:
        for tool_input in resolve_dotted_tool_calls(spans, check.tool):
            if not check.match or match_satisfied(check.match, tool_input):
                calls.append(tool_input)
    return calls


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
