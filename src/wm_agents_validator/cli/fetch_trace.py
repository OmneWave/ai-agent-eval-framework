from __future__ import annotations

import argparse

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
    add_langfuse_args(parser)
    args = parser.parse_args()

    init_langfuse_env(args)
    trace_id = resolve_trace_from_args(args)
    print(f"Fetching trace: {trace_id}")

    result = fetch_and_normalize(
        trace_id,
        retries=args.retries,
        delay_sec=args.delay,
    )
    print_fetch_report(result)


if __name__ == "__main__":
    main()
