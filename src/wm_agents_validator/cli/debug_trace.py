from __future__ import annotations

import argparse
import json
import sys

from wm_agents_validator.cli.langfuse_config import add_langfuse_args, init_langfuse_env
from wm_agents_validator.cli.trace_args import add_trace_args, resolve_trace_from_args
from wm_agents_validator.controller.fetch import run_full_fetch
from wm_agents_validator.report.colors import green, red
from wm_agents_validator.trace.debug_probe import (
    ProbeStep,
    format_env_summary,
    format_probe_url,
    probe_langfuse,
    probe_sdk,
)


def _print_step(step: ProbeStep, *, verbose: bool) -> None:
    status = f"{step.status_code}" if step.status_code is not None else "ERR"
    mark = green("OK ") if step.ok else red("FAIL")
    obs = f" obs={step.observation_count}" if step.observation_count else ""
    print(f"  [{mark}] {step.name}")
    print(f"       {step.method} {format_probe_url(step)}")
    print(f"       status={status}  time={step.duration_ms:.0f}ms{obs}")
    if step.error and not step.ok:
        print(f"       error: {step.error[:200]}")
    if verbose and step.body_preview:
        print(f"       body: {step.body_preview}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Debug Langfuse trace fetch: probe API endpoints step by step",
        epilog=(
            "Example:\n"
            "  LANGFUSE_SECRET_KEY=sk-... LANGFUSE_PUBLIC_KEY=pk-... \\\n"
            "  LANGFUSE_BASE_URL=https://non-prod-ai-logs.wavemakeronline.com \\\n"
            "  uv run debug-trace --trace-id abc123..."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_trace_args(parser)
    add_langfuse_args(parser)
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print response body previews",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output probe results as JSON",
    )
    parser.add_argument(
        "--skip-sdk",
        action="store_true",
        help="Only probe raw HTTP endpoints (skip SDK/rest fetch tests)",
    )
    parser.add_argument(
        "--run-fetch",
        action="store_true",
        help="After probes, run full fetch_trace + normalize and print summary",
    )
    args = parser.parse_args()

    init_langfuse_env(args)
    trace_id = resolve_trace_from_args(args)
    env = format_env_summary()
    base_url = env["LANGFUSE_BASE_URL"]

    http_steps = probe_langfuse(trace_id, base_url)
    sdk_steps = [] if args.skip_sdk else probe_sdk(trace_id)

    if args.json:
        payload = {
            "trace_id": trace_id,
            "env": env,
            "http_probes": [step.__dict__ for step in http_steps],
            "fetch_probes": [step.__dict__ for step in sdk_steps],
        }
        if args.run_fetch:
            try:
                fetch_result = run_full_fetch(trace_id)
                payload["full_fetch"] = fetch_result["summary"]
            except Exception as exc:
                payload["full_fetch_error"] = str(exc)
        print(json.dumps(payload, indent=2, default=str))
        sys.exit(0 if any(s.ok for s in http_steps + sdk_steps) else 1)

    print("=== Langfuse Debug ===")
    print(f"trace_id: {trace_id}")
    print(f"base_url: {base_url}")
    print(f"public_key: {env['LANGFUSE_PUBLIC_KEY']}")
    print(f"secret_key: {env['LANGFUSE_SECRET_KEY']}")
    print(f"ui_url:     {base_url}/project/<project-id>/traces/{trace_id}")
    print()

    print("--- HTTP probes ---")
    for step in http_steps:
        _print_step(step, verbose=args.verbose)

    working = [s for s in http_steps if s.ok]
    print()
    if working:
        best = max(working, key=lambda s: s.observation_count)
        print(
            f"Best HTTP probe: {best.name} "
            f"(status={best.status_code}, observations={best.observation_count})"
        )
    else:
        print("No HTTP probe succeeded.")

    if not args.skip_sdk:
        print()
        print("--- Fetcher probes ---")
        for step in sdk_steps:
            _print_step(step, verbose=args.verbose)

    fetch_ok = False
    if args.run_fetch:
        print()
        print("--- Full fetch + normalize ---")
        try:
            fetch_result = run_full_fetch(trace_id)
            fetch_ok = True
            for key, value in fetch_result["summary"].items():
                print(f"  {key}: {value}")
        except Exception as exc:
            print(f"  FAILED: {exc}")
            sys.exit(1)

    any_ok = any(s.ok for s in http_steps) or any(s.ok for s in sdk_steps) or fetch_ok
    sys.exit(0 if any_ok else 1)


if __name__ == "__main__":
    main()
