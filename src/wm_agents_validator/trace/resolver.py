from __future__ import annotations

from langfuse import Langfuse


def resolve_trace_id(
    trace_id: str = "",
    thread_id: str = "",
    run_id: str = "",
) -> str:
    if trace_id:
        return trace_id
    if thread_id and run_id:
        return Langfuse.create_trace_id(seed=f"{thread_id}:{run_id}")
    raise ValueError(
        "Provide trace_id OR (thread_id AND run_id)"
    )
