from __future__ import annotations

"""Agent scratch files exempt from the scope-creep checks.

The agent may create or read these at its own discretion depending on the use
case, so touching them is never a contract violation. ``run_plugins`` hands the
plugins in ``EXCLUDING_PLUGINS`` a snapshot with the tool calls that only touch
such paths stripped out. Other plugins (e.g. ``trace_health``) still see the
full trace, so a failing notes call is still reported there. WaveMaker's
conventions live here; a different platform would define its own set.
"""

from wm_agents_validator.models.trace_snapshot import (
    TraceSnapshot,
    _span_base_name,
    extract_paths_from_input,
    unwrap_execute_tool,
)

EXCLUDING_PLUGINS: frozenset[str] = frozenset({"input_context", "output"})

# Directory names (matched as a whole path segment, at any depth) whose files
# are agent scratch space, e.g. ``/notes/plan.md``.
WAVEMAKER_EXCLUDED_DIRS: frozenset[str] = frozenset({"notes"})


def is_excluded_path(path: str) -> bool:
    directories = path.strip("/").split("/")[:-1]
    return any(directory in WAVEMAKER_EXCLUDED_DIRS for directory in directories)


def drop_excluded_spans(snapshot: TraceSnapshot) -> TraceSnapshot:
    """Returns a copy of ``snapshot`` without tool calls whose every referenced
    path is excluded. A call that also touches a non-excluded path is kept."""
    kept = []
    for span in snapshot.spans:
        if span.type == "TOOL":
            name, tool_input = unwrap_execute_tool(_span_base_name(span.name), span.input or {})
            paths = extract_paths_from_input(tool_input, name)
            if paths and all(is_excluded_path(p) for p in paths):
                continue
        kept.append(span)
    return snapshot.model_copy(update={"spans": kept})
