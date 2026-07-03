from __future__ import annotations

import argparse
import os

from wm_agents_validator.trace.resolver import resolve_trace_id


def add_trace_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group(
        "Trace lookup",
        "Pass --trace-id directly (preferred), or derive from --thread-id + --run-id",
    )
    group.add_argument(
        "--trace-id",
        default=os.getenv("TRACE_ID", ""),
        help="Langfuse trace ID (preferred). Also reads TRACE_ID env var.",
    )
    group.add_argument(
        "--thread-id",
        default="",
        help="Alternative: thread_id used with --run-id to derive trace ID",
    )
    group.add_argument(
        "--run-id",
        default="",
        help="Alternative: run_id used with --thread-id to derive trace ID",
    )


def resolve_trace_from_args(args: argparse.Namespace) -> str:
    trace_id = (args.trace_id or "").strip()
    thread_id = (args.thread_id or "").strip()
    run_id = (args.run_id or "").strip()

    if not trace_id and not (thread_id and run_id):
        raise SystemExit(
            "Provide --trace-id (preferred) OR both --thread-id and --run-id.\n"
            "Example:\n"
            "  uv run run-verify --contract contracts/foo.yaml --trace-id abc123..."
        )

    try:
        return resolve_trace_id(trace_id, thread_id, run_id)
    except ValueError as e:
        raise SystemExit(str(e)) from e
