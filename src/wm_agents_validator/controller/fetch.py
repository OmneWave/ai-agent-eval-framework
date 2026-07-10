from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wm_agents_validator.models.raw_trace import RawTracePayload
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.report.colors import green, red, yellow
from wm_agents_validator.trace.fetcher import fetch_trace
from wm_agents_validator.trace.normalizer import normalize_trace


@dataclass
class FetchResult:
    payload: RawTracePayload
    snapshot: TraceSnapshot


def fetch_and_normalize(
    trace_id: str,
    *,
    retries: int = 12,
    delay_sec: float = 1.0,
) -> FetchResult:
    payload = fetch_trace(trace_id, retries=retries, delay_sec=delay_sec)
    snapshot = normalize_trace(payload)
    return FetchResult(payload=payload, snapshot=snapshot)


def fetch_summary(result: FetchResult) -> dict[str, Any]:
    snapshot = result.snapshot
    payload = result.payload
    return {
        "observations": len(payload.observations),
        "skill_loads": len(snapshot.skill_loads),
        "skills": [s for load in snapshot.skill_loads for s in load.skill_names],
        "spans": len(snapshot.spans),
        "tools_called": len(snapshot.tools_summary.called),
        "tools_failed": len(snapshot.tools_summary.failed),
        "tools": snapshot.tool_names[:30],
        "delegations": len(snapshot.delegations),
        "errors": len(snapshot.errors),
        "entry_agent": snapshot.entry_agent,
        "status": snapshot.status,
        "user_prompt_preview": (snapshot.user_prompt or "")[:120],
    }


def run_full_fetch(trace_id: str) -> dict[str, Any]:
    result = fetch_and_normalize(trace_id, retries=1, delay_sec=0)
    return {"summary": fetch_summary(result)}


def print_fetch_report(result: FetchResult) -> None:
    snapshot = result.snapshot
    summary = fetch_summary(result)

    print("\n=== Trace Snapshot Summary ===")
    print(f"trace_id:     {snapshot.trace_id}")
    print(f"session_id:   {snapshot.session_id}")
    print(f"entry_agent:  {snapshot.entry_agent}")
    status_color = {"success": green, "error": red}.get(snapshot.status, yellow)
    print(f"status:       {status_color(snapshot.status)}")
    prompt = snapshot.user_prompt or ""
    print(f"user_prompt:  {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print(f"skills:       {summary['skills']}")
    tools = snapshot.tool_names[:20]
    print(f"tools:        {tools}{'...' if len(snapshot.tool_names) > 20 else ''}")
    if snapshot.tools_summary.failed:
        print("failed_tools:")
        for failure in snapshot.tools_summary.failed[:5]:
            print(f"  - {failure.name}: {failure.error_message}")
    tool_spans = [s for s in snapshot.spans if s.type == "TOOL"]
    print(f"spans:        {len(snapshot.spans)} total ({len(tool_spans)} tools)")
    print(f"\nObservations: {summary['observations']}")
    print(f"Skill loads:  {summary['skill_loads']}")
    print(f"Tools called: {summary['tools_called']}")
    print(f"Tools failed: {summary['tools_failed']}")
    print(f"Delegations:  {summary['delegations']}")
    print(f"Errors:       {summary['errors']}")
