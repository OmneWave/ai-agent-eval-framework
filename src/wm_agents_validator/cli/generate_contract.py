from __future__ import annotations

import argparse
from pathlib import Path

from wm_agents_validator.cli.langfuse_config import add_langfuse_args, init_langfuse_env
from wm_agents_validator.cli.trace_args import add_trace_args, resolve_trace_from_args
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
    parser.add_argument("--retries", type=int, default=12)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--workflow", required=True, help="Value for the contract's `workflow` field")
    parser.add_argument("--contract-version", dest="contract_version", default="1.0.0")
    parser.add_argument("--out", required=True, help="Output contract YAML path")
    add_langfuse_args(parser)
    args = parser.parse_args()

    if args.from_file:
        snapshot = TraceSnapshot.model_validate_json(Path(args.from_file).read_text(encoding="utf-8"))
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
