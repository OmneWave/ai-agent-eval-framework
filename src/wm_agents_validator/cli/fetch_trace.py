from __future__ import annotations

import argparse
from pathlib import Path

from wm_agents_validator.cli.langfuse_config import add_langfuse_args, init_langfuse_env
from wm_agents_validator.cli.trace_args import add_trace_args, resolve_trace_from_args
from wm_agents_validator.controller.fetch import fetch_and_normalize, print_fetch_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and inspect a Langfuse trace by trace ID",
        epilog="Example: uv run fetch-trace --trace-id abc123...",
    )
    add_trace_args(parser)
    parser.add_argument("--retries", type=int, default=12)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full TraceSnapshot as JSON instead of the summary report",
    )
    parser.add_argument(
        "--out",
        help="Write the TraceSnapshot JSON to this file (in addition to console output)",
    )
    add_langfuse_args(parser)
    args = parser.parse_args()

    init_langfuse_env(args)
    trace_id = resolve_trace_from_args(args)
    if not args.json:
        print(f"Fetching trace: {trace_id}")

    result = fetch_and_normalize(
        trace_id,
        retries=args.retries,
        delay_sec=args.delay,
    )

    if args.json:
        print(result.snapshot.model_dump_json(indent=2))
    else:
        print_fetch_report(result)

    if args.out:
        Path(args.out).write_text(result.snapshot.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nSnapshot written to {args.out}")


if __name__ == "__main__":
    main()
