from __future__ import annotations

import argparse
from pathlib import Path

from wm_agents_validator.cli.langfuse_config import add_langfuse_args, get_langfuse_environment, init_langfuse_env
from wm_agents_validator.cli.trace_args import add_trace_args, parse_metadata_filters, resolve_trace_from_args
from wm_agents_validator.comparison.sources import MetadataFilterTraceSource
from wm_agents_validator.controller.fetch import fetch_and_normalize
from wm_agents_validator.controller.generate_contract import generate_contract
from wm_agents_validator.models.trace_snapshot import TraceSnapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a starter workflow contract YAML from an observed trace",
        epilog=(
            "Examples:\n"
            "  uv run generate-contract --trace-id abc123... --workflow screenshot_to_code "
            "--out contracts/new.yaml\n"
            "  uv run generate-contract --filter projectid=WMPRJ... --limit 1 "
            "--workflow screenshot_to_code --out contracts/new.yaml\n"
            "  uv run generate-contract --from-file test_1.json --workflow screenshot_to_code "
            "--out contracts/new.yaml\n"
            "\n"
            "The output is a starting point, not a finished contract -- it only knows what one "
            "trace happened to do. Review the printed warnings and the generated `output`/`match` "
            "entries before trusting it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--from-file",
        help="Path to a previously saved TraceSnapshot JSON (e.g. from `fetch-trace --out`), instead of fetching live",
    )
    add_trace_args(parser)
    filter_group = parser.add_argument_group(
        "Trace lookup by metadata",
        "Alternative to --trace-id: find the trace(s) via a server-side metadata filter",
    )
    filter_group.add_argument(
        "--filter",
        action="append",
        metavar="KEY=VALUE",
        help="Metadata key=value to find a trace by (server-side, exact match). Repeatable -- "
        "each occurrence ANDs another condition, e.g. --filter projectid=WMPRJ... "
        "--filter environment=stage-ai. Generates from the single most recent match.",
    )
    filter_group.add_argument(
        "--limit",
        type=int,
        default=1,
        help="--filter mode: max candidate traces to pull before picking the most recent one "
        "(default: 1). Raise this only if you expect --filter to be ambiguous and want to "
        "see how many traces actually match.",
    )
    parser.add_argument("--retries", type=int, default=12)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--workflow", required=True, help="Value for the contract's `workflow` field")
    parser.add_argument("--contract-version", dest="contract_version", default="1.0.0")
    parser.add_argument("--out", required=True, help="Output contract YAML path")
    add_langfuse_args(parser)
    args = parser.parse_args()

    has_trace_id = bool(args.trace_id.strip()) or bool(args.thread_id and args.run_id)
    modes = [bool(args.from_file), bool(args.filter), has_trace_id]
    if sum(modes) > 1:
        parser.error("Provide exactly one of --from-file, --trace-id (or --thread-id+--run-id), or --filter")
    if sum(modes) == 0:
        parser.error("Provide one of --from-file, --trace-id (or --thread-id+--run-id), or --filter")

    if args.from_file:
        snapshot = TraceSnapshot.model_validate_json(Path(args.from_file).read_text(encoding="utf-8"))
    elif args.filter:
        init_langfuse_env(args)
        try:
            metadata_filters = parse_metadata_filters(args.filter)
        except ValueError as exc:
            parser.error(str(exc))
        trace_ids = MetadataFilterTraceSource(
            metadata_filters, limit=args.limit, environment=get_langfuse_environment()
        ).get_trace_ids()
        if not trace_ids:
            parser.error(f"No traces found for filter: {args.filter}")
        if len(trace_ids) > 1:
            print(
                f"Found {len(trace_ids)} traces matching filter; using the most recent: "
                f"{trace_ids[0]} (pass --limit 1, or a specific --trace-id, to avoid ambiguity)"
            )
        print(f"Fetching trace: {trace_ids[0]}")
        snapshot = fetch_and_normalize(trace_ids[0], retries=args.retries, delay_sec=args.delay).snapshot
    else:
        init_langfuse_env(args)
        trace_id = resolve_trace_from_args(args)
        print(f"Fetching trace: {trace_id}")
        snapshot = fetch_and_normalize(trace_id, retries=args.retries, delay_sec=args.delay).snapshot

    result = generate_contract(snapshot, workflow=args.workflow, contract_version=args.contract_version)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.yaml_text, encoding="utf-8")
    print(f"Contract written to {out_path}")

    if result.warnings:
        print("\nReview before use:")
        for warning in result.warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    main()
