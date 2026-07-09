from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wm_agents_validator.cli.langfuse_config import add_langfuse_args, init_langfuse_env
from wm_agents_validator.cli.trace_args import add_trace_args, resolve_trace_from_args
from wm_agents_validator.controller.verify import load_snapshot, run_verification
from wm_agents_validator.models.plugin_result import EvalContext
from wm_agents_validator.plugins.registry import DEFAULT_PLUGINS, list_plugins
from wm_agents_validator.report.console_reporter import print_console_report, write_json_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify agent trace against workflow contract",
        epilog=(
            "Example: uv run run-verify --contract contracts/foo.yaml --trace-id abc123..."
        ),
    )
    parser.add_argument("--contract", help="Path to WorkflowContract YAML")
    add_trace_args(parser)
    parser.add_argument("--snapshot", help="Use pre-built TraceSnapshot JSON instead of fetching")
    parser.add_argument(
        "--context",
        default="{}",
        help="Optional. Only for path-templating helpers still exposed via EvalContext.bindings. Default: none.",
    )
    parser.add_argument(
        "--plugins",
        help=f"Comma-separated plugin names (default: all). Available: {', '.join(list_plugins())}",
    )
    parser.add_argument("--out", help="Write VerificationReport JSON to file")
    parser.add_argument(
        "--dump-snapshot",
        help="Write the fetched/loaded TraceSnapshot JSON to this file",
    )
    parser.add_argument(
        "--print-snapshot",
        action="store_true",
        help="Print the TraceSnapshot JSON to the console",
    )
    parser.add_argument("--list-plugins", action="store_true", help="List available plugins and exit")
    parser.add_argument("--retries", type=int, default=12)
    parser.add_argument("--delay", type=float, default=1.0)
    add_langfuse_args(parser)
    args = parser.parse_args()

    if args.list_plugins:
        for name in list_plugins():
            default = " (default)" if name in DEFAULT_PLUGINS else ""
            print(f"  {name}{default}")
        sys.exit(0)

    if not args.contract:
        parser.error("--contract is required unless using --list-plugins")

    context = EvalContext(bindings=json.loads(args.context))
    snapshot = load_snapshot(args.snapshot) if args.snapshot else None
    trace_id = None

    if snapshot is None:
        init_langfuse_env(args)
        trace_id = resolve_trace_from_args(args)
        print(f"Fetching trace: {trace_id}")

    plugin_names = [p.strip() for p in args.plugins.split(",")] if args.plugins else None
    result = run_verification(
        args.contract,
        snapshot=snapshot,
        trace_id=trace_id,
        context=context,
        plugins=plugin_names,
        retries=args.retries,
        delay_sec=args.delay,
    )

    if args.print_snapshot:
        print(result.snapshot.model_dump_json(indent=2))

    print_console_report(result.report)
    if args.out:
        write_json_report(result.report, args.out)
        print(f"\nReport written to {args.out}")
    if args.dump_snapshot:
        Path(args.dump_snapshot).write_text(
            result.snapshot.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"Snapshot written to {args.dump_snapshot}")

    sys.exit(0 if result.report.passed else 1)


if __name__ == "__main__":
    main()
