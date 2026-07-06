from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wm_agents_validator.cli.langfuse_config import add_langfuse_args, init_langfuse_env
from wm_agents_validator.comparison.aggregator import merge_reports
from wm_agents_validator.comparison.pipeline import ComparisonPipeline
from wm_agents_validator.comparison.sources import ExplicitTraceIdSource, TimeRangeTraceSource
from wm_agents_validator.contracts.loader import load_contract
from wm_agents_validator.report.html_comparison_renderer import HtmlComparisonRenderer


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare multiple traces (e.g. across LLMs and/or contracts, or over a "
        "time range) and render a self-contained HTML report.",
        epilog=(
            "Examples:\n"
            "  # One contract, several LLMs\n"
            "  uv run compare-traces --contract contracts/foo.yaml "
            "--trace-ids abc123,def456 --out report.html\n\n"
            "  # Several contracts, each with its own trace(s) (repeat both flags,\n"
            "  # in matching order)\n"
            "  uv run compare-traces \\\n"
            "    --contract contracts/foo.yaml --trace-ids gpt4-trace,claude-trace \\\n"
            "    --contract contracts/bar.yaml --trace-ids gpt4-trace-2,claude-trace-2 \\\n"
            "    --out report.html\n\n"
            "  # Time range (single contract only)\n"
            "  uv run compare-traces --contract contracts/foo.yaml "
            "--from 2026-07-01T00:00:00Z --to 2026-07-02T00:00:00Z "
            "--user-id alice --out report.html"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--contract",
        action="append",
        required=True,
        help="Path to a WorkflowContract YAML. Repeat to compare multiple contracts, "
        "pairing each with its own --trace-ids (same order).",
    )

    source_group = parser.add_argument_group(
        "Trace selection (pick one)",
        "Either --trace-ids (repeatable, one per --contract), or a --from/--to time range",
    )
    source_group.add_argument(
        "--trace-ids",
        action="append",
        help="Comma-separated Langfuse trace IDs to compare directly. Repeat once per "
        "--contract when comparing multiple contracts.",
    )
    source_group.add_argument("--from", dest="from_ts", help="Range start, ISO-8601 (e.g. 2026-07-01T00:00:00Z)")
    source_group.add_argument("--to", dest="to_ts", help="Range end, ISO-8601")
    source_group.add_argument(
        "--user-id",
        help="Langfuse native userId to filter time-range traces by",
    )
    source_group.add_argument(
        "--limit", type=int, default=50, help="Max traces to pull in time-range mode (default: 50)"
    )

    parser.add_argument(
        "--user-id-key",
        default="user_id",
        help="Metadata key holding the user id to display/group by in the report "
        "(default: 'user_id'). Use this if your traces stash it under a different "
        "trace metadata key.",
    )
    parser.add_argument(
        "--model",
        help="Only include traces whose captured model_name matches this value",
    )
    parser.add_argument("--out", required=True, help="Output HTML file path")
    parser.add_argument("--retries", type=int, default=12)
    parser.add_argument("--delay", type=float, default=1.0)
    add_langfuse_args(parser)
    return parser


def _resolve_contract_trace_groups(
    contracts: list[str], trace_id_groups: list[str]
) -> list[tuple[str, list[str]]]:
    """Pairs `--contract` entries up with `--trace-ids` entries.

    - Exactly one `--contract`: every `--trace-ids` occurrence is pooled
      together under that one contract (so repeating `--trace-ids` is just a
      convenience for listing lots of IDs, not a multi-contract signal).
    - Multiple `--contract` entries: requires exactly as many `--trace-ids`
      entries, paired up pairwise in command-line order.
    """
    if len(contracts) == 1:
        pooled = [t.strip() for group in trace_id_groups for t in group.split(",") if t.strip()]
        return [(contracts[0], pooled)]

    if len(trace_id_groups) != len(contracts):
        raise ValueError(
            "When passing multiple --contract values, pass exactly as many --trace-ids "
            "values, one per --contract, in matching order."
        )
    return [
        (contract, [t.strip() for t in group.split(",") if t.strip()])
        for contract, group in zip(contracts, trace_id_groups)
    ]


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    has_explicit_ids = bool(args.trace_ids)
    has_time_range = bool(args.from_ts or args.to_ts)
    if has_explicit_ids == has_time_range:
        parser.error("Provide exactly one of --trace-ids OR --from/--to")
    if has_time_range and not (args.from_ts and args.to_ts):
        parser.error("--from and --to must both be provided together")
    if has_time_range and len(args.contract) > 1:
        parser.error("--from/--to time-range mode supports only a single --contract")

    init_langfuse_env(args)

    if has_explicit_ids:
        try:
            groups = _resolve_contract_trace_groups(args.contract, args.trace_ids)
        except ValueError as exc:
            parser.error(str(exc))
        pipelines = [
            ComparisonPipeline(
                contract=load_contract(contract_path),
                source=ExplicitTraceIdSource(trace_ids),
                user_id_key=args.user_id_key,
                model_filter=args.model,
                retries=args.retries,
                delay_sec=args.delay,
            )
            for contract_path, trace_ids in groups
        ]
    else:
        source = TimeRangeTraceSource(
            args.from_ts, args.to_ts, user_id=args.user_id, limit=args.limit
        )
        pipelines = [
            ComparisonPipeline(
                contract=load_contract(args.contract[0]),
                source=source,
                user_id_key=args.user_id_key,
                model_filter=args.model,
                retries=args.retries,
                delay_sec=args.delay,
            )
        ]

    print(f"Discovering and evaluating traces across {len(pipelines)} contract(s)...")
    report = merge_reports([pipeline.build_report() for pipeline in pipelines])

    if not report.rows:
        print("No traces found for the given selection.")
        sys.exit(1)

    html = HtmlComparisonRenderer().render(report)
    Path(args.out).write_text(html, encoding="utf-8")

    passed = sum(1 for r in report.rows if r.status == "ok" and r.passed)
    errored = sum(1 for r in report.rows if r.status == "error")
    print(
        f"Compared {len(report.rows)} trace(s) across {len(report.contract_ids)} contract(s): "
        f"{passed} passed, {len(report.rows) - passed - errored} failed, {errored} errored."
    )
    print(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
