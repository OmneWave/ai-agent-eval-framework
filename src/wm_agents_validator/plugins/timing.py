"""Shared span-duration helpers, used by several plugins to report a "time
spent on X" check alongside their own pass/fail checks -- e.g. input_context
reports input-gathering time, output reports output-generation time,
tool_calls reports total tool-call time, trace_health reports error time.
Centralized here (rather than duplicated per plugin, or all living in one
plugin other plugins import from) since none of these plugins is a more
natural owner of duration math than another.
"""
from __future__ import annotations

from datetime import datetime

from wm_agents_validator.models.trace_snapshot import SpanRecord

# Tool calls whose purpose is pulling information INTO context -- exploring
# the codebase/API, looking things up before acting. Intentionally broader
# than input_context.py's own "retrieved context" definition (which excludes
# search/scan tools like grep_in_files/find_files_by_glob as merely a *search
# scope*, not retrieved content) -- this bucket answers a different question,
# "how much wall-clock time went into gathering info", where a search call
# still counts as time spent gathering.
INPUT_GATHERING_TOOLS = frozenset(
    {
        "read_files",
        "grep_in_files",
        "find_files_by_glob",
        "get_tool_schema",
        "platform_getServiceDetails",
        "platform_listPageVariables",
        "platform_listPages",
        "platform_getSessionResource",
    }
)

# Tool calls that produce or change output -- file writes plus the platform's
# own create/update actions on variables, widgets, and pages.
OUTPUT_GENERATION_TOOLS = frozenset(
    {
        "write_file",
        "edit_file_content",
        "delete_file",
        "ui_createApiAwareVariable",
        "ui_createNonApiAwareVariable",
        "ui_updateVariable",
        "platform_createWebPage",
        "platform_compile",
    }
)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def span_duration_ms(span: SpanRecord) -> float | None:
    """Wall-clock duration of one span, or ``None`` if either timestamp is
    missing/unparseable -- Langfuse doesn't guarantee ``end_time`` on every
    observation, so callers summing durations must treat missing spans as
    "unknown", not zero.
    """
    start = parse_timestamp(span.timestamp)
    end = parse_timestamp(span.end_time)
    if start is None or end is None:
        return None
    return max((end - start).total_seconds() * 1000, 0.0)


def sum_duration_ms(spans: list[SpanRecord]) -> float:
    return sum(d for d in (span_duration_ms(s) for s in spans) if d is not None)


def fmt_ms(value: float | None) -> str:
    return f"{value:,.0f}ms" if value is not None else "n/a"
