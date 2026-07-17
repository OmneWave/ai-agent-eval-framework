from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wm_agents_validator.cli.langfuse_config import add_langfuse_args, get_langfuse_environment, init_langfuse_env
from wm_agents_validator.cli.trace_args import parse_metadata_filters
from wm_agents_validator.comparison.aggregator import merge_reports
from wm_agents_validator.comparison.pipeline import ComparisonPipeline
from wm_agents_validator.comparison.sources import (
    ContentSearchTraceSource,
    ExplicitTraceIdSource,
    MetadataFilterTraceSource,
    TimeRangeTraceSource,
)
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
            "  # Several contracts, each with its own trace(s) -- embed the ids directly\n"
            "  # in --contract ('path:id1,id2') so each one is self-contained; no need to\n"
            "  # keep a separate --trace-ids list in matching order\n"
            "  uv run compare-traces \\\n"
            "    --contract contracts/foo.yaml:gpt4-trace,claude-trace \\\n"
            "    --contract contracts/bar.yaml:gpt4-trace-2,claude-trace-2 \\\n"
            "    --out report.html\n\n"
            "  # Time range (single contract only)\n"
            "  uv run compare-traces --contract contracts/foo.yaml "
            "--from 2026-07-01T00:00:00Z --to 2026-07-02T00:00:00Z "
            "--user-id alice --out report.html\n\n"
            "  # Metadata filter, no time range needed (single contract only)\n"
            "  uv run compare-traces --contract contracts/foo.yaml "
            "--filter workflow_name=create_variable_binding --filter model_name=glm-5 "
            "--limit 20 --out report.html\n\n"
            "  # Different contract PER project -- embed a key=value filter directly\n"
            "  # in --contract instead of a trace id, so each project pulls its own\n"
            "  # matching trace and is verified against its own page's contract\n"
            "  uv run compare-traces \\\n"
            "    --contract contracts/pages/login.yaml:projectid=WMPRJ1 \\\n"
            "    --contract contracts/pages/dashboard.yaml:projectid=WMPRJ2 \\\n"
            "    --out report.html\n\n"
            "  # Content search: no --trace-ids/--from-to/--filter at all -- keeps searching\n"
            "  # the most recent traces until --limit actually match (single contract only)\n"
            "  uv run compare-traces --contract contracts/foo.yaml "
            "--user-prompt-contains findByTags --skill-name-contains api_binding "
            "--limit 20 --out report.html"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--contract",
        action="append",
        required=True,
        metavar="CONTRACT_PATH[:TRACE_ID[,TRACE_ID...]|:KEY=VALUE[,KEY=VALUE...]]",
        help="Path to a WorkflowContract YAML. To compare multiple contracts, repeat "
        "this flag with each trace's ids embedded directly, e.g. "
        "'path/to.yaml:id1,id2' -- this keeps each contract self-contained instead of "
        "relying on a separate --trace-ids list lining up by position. Or embed a "
        "key=value metadata filter instead of ids, e.g. 'path/to.yaml:projectid=WMPRJ1', "
        "so each contract pulls its own matching trace by metadata -- lets a batch of "
        "different contracts each run against a different project/page in one command. "
        "A single bare path (no ':') works with --trace-ids, --from/--to, or --filter as before.",
    )

    source_group = parser.add_argument_group(
        "Trace selection (pick one)",
        "Either --trace-ids / ids embedded in --contract, a --from/--to time range, or --filter",
    )
    source_group.add_argument(
        "--trace-ids",
        action="append",
        help="Comma-separated Langfuse trace IDs to compare directly. Only usable with "
        "a single, bare --contract (no embedded ids) -- for multiple contracts, embed "
        "each one's ids in its own --contract value instead.",
    )
    source_group.add_argument("--from", dest="from_ts", help="Range start, ISO-8601 (e.g. 2026-07-01T00:00:00Z)")
    source_group.add_argument("--to", dest="to_ts", help="Range end, ISO-8601")
    source_group.add_argument(
        "--filter",
        action="append",
        metavar="KEY=VALUE",
        help="Metadata key=value to filter traces by (server-side, exact match). Repeatable -- "
        "a DIFFERENT key ANDs another condition, e.g. --filter workflow_name=foo "
        "--filter model_name=glm-5. The SAME key repeated ORs across those values instead, "
        "e.g. --filter projectid=WMPRJ1 --filter projectid=WMPRJ2 matches either project. "
        "Works standalone, no --from/--to needed. Single contract only, like time-range mode.",
    )
    source_group.add_argument(
        "--user-id",
        help="Langfuse native userId to filter time-range traces by",
    )
    source_group.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Time-range/--filter mode: max candidate traces to pull. Content-search mode "
        "(--user-prompt-contains/--skill-name-contains with no other selection mode): max "
        "*matching* traces to find, searching the most recent traces until this many match "
        "or a safety cap on candidates scanned is hit. (default: 50)",
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
    parser.add_argument(
        "--user-prompt-contains",
        dest="user_prompt_contains",
        help="Only include traces whose user_prompt (normalized trace input) contains this text "
        "(case-insensitive substring, client-side -- Langfuse has no server-side filter for "
        "input content, confirmed against a live instance). Applied after fetching, on top of "
        "whichever trace-selection mode you used.",
    )
    parser.add_argument(
        "--skill-name-contains",
        dest="skill_name_contains",
        help="Only include traces where any loaded skill name contains this text (case-insensitive "
        "substring, client-side -- skill_names isn't a native Langfuse column, it's derived "
        "during normalization from load_skill tool-call spans, so there's no server-side filter "
        "for it either). Applied after fetching, on top of whichever trace-selection mode you used.",
    )
    parser.add_argument("--out", required=True, help="Output HTML file path")
    parser.add_argument("--retries", type=int, default=12)
    parser.add_argument("--delay", type=float, default=1.0)
    add_langfuse_args(parser)
    return parser


def _split_contract_arg(value: str) -> tuple[str, list[str], list[tuple[str, str]]]:
    """Splits one `--contract` value into (path, embedded_trace_ids, embedded_metadata_filters).

    `path/to.yaml:id1,id2` attaches trace ids directly to that contract, so the
    (contract, trace ids) association is explicit and self-contained right
    there in a single flag, instead of depending on a same-order `--trace-ids`
    occurrence elsewhere on the command line.

    `path/to.yaml:key=value` (or `key=value,key2=value2`) instead attaches a
    metadata filter -- so a batch of contracts can each pull *their own*
    matching trace by e.g. `projectid`, rather than all of them sharing one
    trace-id list or one global `--filter`. Detected by the presence of `=`
    in the embedded segment; mixing ids and filters after the same `:` isn't
    supported (raises ValueError naming the bad value).

    A bare path (no `:`) has neither and falls back to `--trace-ids`/
    `--from`-`--to`/`--filter`.
    """
    if ":" not in value:
        return value, [], []
    path, rest_part = value.split(":", 1)
    path = path.strip()
    segments = [s.strip() for s in rest_part.split(",") if s.strip()]
    has_eq = [("=" in s) for s in segments]
    if any(has_eq) and not all(has_eq):
        raise ValueError(
            f"--contract {value!r}: can't mix trace ids and key=value filters after ':' -- "
            "use all ids (path:id1,id2) or all key=value filters (path:key=value,key2=value2)"
        )
    if segments and all(has_eq):
        return path, [], parse_metadata_filters(segments)
    return path, segments, []


def _resolve_contract_trace_groups(
    contracts: list[str], trace_id_groups: list[str]
) -> list[tuple[str, list[str]]]:
    """Builds (contract_path, trace_ids) groups from `--contract` values.

    - A single `--contract` (bare, or with embedded ids): any `--trace-ids`
      occurrences are pooled in on top of its embedded ids, if any -- this is
      just a convenience for listing lots of ids for the one contract.
    - Multiple `--contract` values: each one must embed its own trace ids
      (`path:id1,id2`). This is what makes the contract<->trace association
      explicit instead of relying on a second `--trace-ids` list staying in
      sync by position -- so no embedded ids anywhere, or a stray
      `--trace-ids`, is a user error here rather than silently mispairing.
    """
    parsed = [_split_contract_arg(c) for c in contracts]
    pooled_trace_ids = [t.strip() for group in trace_id_groups for t in group.split(",") if t.strip()]

    if len(parsed) == 1:
        path, embedded_ids, _filters = parsed[0]
        return [(path, embedded_ids + pooled_trace_ids)]

    missing_embedded = [path for path, ids, _filters in parsed if not ids]
    if missing_embedded or pooled_trace_ids:
        raise ValueError(
            "When passing multiple --contract values, each one must embed its own "
            "trace ids, e.g. --contract path/to.yaml:id1,id2 "
            "--contract path/to/other.yaml:id3,id4 -- --trace-ids isn't supported "
            "alongside multiple --contract values."
        )
    return [(path, ids) for path, ids, _filters in parsed]


def _resolve_contract_filter_groups(contracts: list[str]) -> list[tuple[str, list[tuple[str, str]]]]:
    """Builds (contract_path, metadata_filter_pairs) groups from `--contract`
    values with embedded `path:key=value[,key2=value2]` filters -- lets each
    contract in a batch pull its own matching trace(s) by e.g. `projectid`,
    instead of all contracts sharing one global `--filter`.

    Every `--contract` value must embed its own filter, same self-contained-
    association principle as embedded trace ids above: no silent pairing by
    position, no accidental sharing of one filter across contracts that were
    each meant to pull a different trace.
    """
    parsed = [_split_contract_arg(c) for c in contracts]
    missing_embedded = [path for path, _ids, filters in parsed if not filters]
    if missing_embedded:
        raise ValueError(
            "Every --contract value must embed its own key=value filter when using this mode, "
            "e.g. --contract path/to.yaml:projectid=WMPRJ1 --contract path/to/other.yaml:projectid=WMPRJ2 "
            f"-- missing an embedded filter on: {missing_embedded}"
        )
    return [(path, filters) for path, _ids, filters in parsed]


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        contract_specs = [_split_contract_arg(c) for c in args.contract]
    except ValueError as exc:
        parser.error(str(exc))
        return
    has_embedded_ids = any(ids for _path, ids, _filters in contract_specs)
    has_embedded_filters = any(filters for _path, _ids, filters in contract_specs)
    has_explicit_ids = bool(args.trace_ids) or has_embedded_ids
    has_time_range = bool(args.from_ts or args.to_ts)
    has_filter = bool(args.filter)
    has_content_filter = bool(args.user_prompt_contains or args.skill_name_contains)
    explicit_modes = sum([has_explicit_ids, has_time_range, has_filter, has_embedded_filters])
    if explicit_modes > 1:
        parser.error(
            "Provide exactly one of --trace-ids / ids embedded in --contract, OR "
            "--from/--to, OR --filter, OR key=value filters embedded in --contract "
            "(and don't mix embedded ids with embedded filters across --contract values)"
        )
    if explicit_modes == 0 and not has_content_filter:
        parser.error(
            "Provide exactly one of --trace-ids / ids embedded in --contract, OR "
            "--from/--to, OR --filter, OR key=value filters embedded in --contract, OR "
            "--user-prompt-contains/--skill-name-contains "
            "(content search mode -- searches the most recent traces until --limit matches)"
        )
    # No explicit mode, but a content filter alone -> search mode: keep pulling
    # candidates until --limit traces actually match, rather than filtering a
    # fixed batch from one of the other three modes.
    has_content_search = explicit_modes == 0
    if has_time_range and not (args.from_ts and args.to_ts):
        parser.error("--from and --to must both be provided together")
    if (has_time_range or has_filter or has_content_search) and len(args.contract) > 1:
        parser.error("--from/--to, --filter, and content-search modes support only a single --contract")
    if (has_time_range or has_filter) and has_embedded_ids:
        parser.error("--from/--to and --filter modes don't take trace ids embedded in --contract")

    init_langfuse_env(args)
    environment = get_langfuse_environment()

    if has_embedded_filters:
        try:
            filter_groups = _resolve_contract_filter_groups(args.contract)
        except ValueError as exc:
            parser.error(str(exc))
        pipelines = [
            ComparisonPipeline(
                contract=load_contract(contract_path),
                source=MetadataFilterTraceSource(filters, limit=args.limit, environment=environment),
                user_id_key=args.user_id_key,
                model_filter=args.model,
                user_prompt_filter=args.user_prompt_contains,
                skill_name_filter=args.skill_name_contains,
                retries=args.retries,
                delay_sec=args.delay,
            )
            for contract_path, filters in filter_groups
        ]
    elif has_explicit_ids:
        try:
            groups = _resolve_contract_trace_groups(args.contract, args.trace_ids or [])
        except ValueError as exc:
            parser.error(str(exc))
        empty = [path for path, ids in groups if not ids]
        if empty:
            parser.error(f"No trace ids resolved for: {empty}")
        pipelines = [
            ComparisonPipeline(
                contract=load_contract(contract_path),
                source=ExplicitTraceIdSource(trace_ids),
                user_id_key=args.user_id_key,
                model_filter=args.model,
                user_prompt_filter=args.user_prompt_contains,
                skill_name_filter=args.skill_name_contains,
                retries=args.retries,
                delay_sec=args.delay,
            )
            for contract_path, trace_ids in groups
        ]
    elif has_filter:
        try:
            metadata_filters = parse_metadata_filters(args.filter)
        except ValueError as exc:
            parser.error(str(exc))
        source = MetadataFilterTraceSource(metadata_filters, limit=args.limit, environment=environment)
        pipelines = [
            ComparisonPipeline(
                contract=load_contract(args.contract[0]),
                source=source,
                user_id_key=args.user_id_key,
                model_filter=args.model,
                user_prompt_filter=args.user_prompt_contains,
                skill_name_filter=args.skill_name_contains,
                retries=args.retries,
                delay_sec=args.delay,
            )
        ]
    elif has_content_search:
        source = ContentSearchTraceSource(
            user_prompt_contains=args.user_prompt_contains,
            skill_name_contains=args.skill_name_contains,
            limit=args.limit,
            environment=environment,
        )
        pipelines = [
            ComparisonPipeline(
                contract=load_contract(args.contract[0]),
                source=source,
                user_id_key=args.user_id_key,
                model_filter=args.model,
                user_prompt_filter=args.user_prompt_contains,
                skill_name_filter=args.skill_name_contains,
                retries=args.retries,
                delay_sec=args.delay,
            )
        ]
    else:
        source = TimeRangeTraceSource(
            args.from_ts, args.to_ts, user_id=args.user_id, limit=args.limit, environment=environment
        )
        pipelines = [
            ComparisonPipeline(
                contract=load_contract(args.contract[0]),
                source=source,
                user_id_key=args.user_id_key,
                model_filter=args.model,
                user_prompt_filter=args.user_prompt_contains,
                skill_name_filter=args.skill_name_contains,
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
