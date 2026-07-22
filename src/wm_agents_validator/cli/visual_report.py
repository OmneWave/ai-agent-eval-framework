"""
visual-report: Side-by-side visual comparison report for a WM project.

For each trace found under a projectId, extracts:
  - Page name          from platform_createWebPage (where pageType == "PAGE")
  - Input screenshot   from the wm_screenshot_to_code_agent span input (Figma design)
  - Generated preview  from the ui_getPageScreenshot tool output
  - Project / Trace ID

Produces a standalone HTML file with one card per trace.

Usage:
  uv run visual-report --project-id WMPRJ001 --out report.html
  uv run visual-report --project-id WMPRJ001 --project-id WMPRJ002 --out report.html
  uv run visual-report --project-id WMPRJ001 --limit 10 --out report.html
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wm_agents_validator.cli.langfuse_config import (
    add_langfuse_args,
    get_langfuse_environment,
    init_langfuse_env,
)
from wm_agents_validator.comparison.sources import MetadataFilterTraceSource
from wm_agents_validator.controller.fetch import fetch_and_normalize
from wm_agents_validator.models.raw_trace import RawTracePayload
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.trace.screenshots import (
    base_tool_name as _base_tool_name,
    extract_image as _extract_image,
    extract_input_screenshot as _extract_input_screenshot,
    extract_output_screenshot as _extract_output_screenshot,
    iter_spans_by_name as _iter_spans_by_name,
    iter_tool_spans as _iter_tool_spans,
)

# ---------------------------------------------------------------------------
# Per-trace data extraction
# ---------------------------------------------------------------------------

_PAGES_PATH_RE = re.compile(r"[/\\]pages[/\\]([^/\\]+)[/\\]")


def _extract_page_name(snapshot: TraceSnapshot) -> str | None:
    """
    Find the page name.

    1. platform_createWebPage (pageInfo.pageType == "PAGE") — new pages only
    2. write_file paths  — works for pre-existing pages like Login that are
       never created via platform_createWebPage
    """
    for span in _iter_tool_spans(snapshot, "platform_createWebPage"):
        inp = span.input or {}
        page_info = inp.get("pageInfo") or {}
        if page_info.get("pageType") == "PAGE":
            return inp.get("pageName")

    # Fallback: infer from write_file paths (src/main/webapp/pages/<Name>/...)
    for span in _iter_tool_spans(snapshot, "write_file"):
        path: str = (span.input or {}).get("file_path", "")
        m = _PAGES_PATH_RE.search(path)
        if m:
            return m.group(1)

    return None


_DEBUG_INSPECT = {"start_new_conversation_with_agent", "ui_getPageScreenshot"}


def _debug_spans(snapshot: TraceSnapshot, payload: RawTracePayload | None = None) -> None:
    print("  [debug] spans:")
    for span in snapshot.spans:
        has_input = span.input is not None
        has_output = span.output is not None
        print(f"    type={span.type:<12} in={has_input!s:<5} out={has_output!s:<5} name={span.name}")
        base = _base_tool_name(span.name)
        if base in _DEBUG_INSPECT:
            if span.input is not None:
                print(f"      INPUT  keys={list(span.input.keys()) if isinstance(span.input, dict) else type(span.input).__name__}")
                raw = json.dumps(span.input, default=str)
                print(f"      INPUT  (first 400): {raw[:400]}")
            if span.output is not None:
                raw = json.dumps(span.output, default=str)
                print(f"      OUTPUT (first 400): {raw[:400]}")

    if payload:
        print("  [debug] raw trace.input keys:",
              list(payload.trace.keys()) if payload.trace else "trace=None")
        if payload.trace:
            raw_in = payload.trace.get("input")
            preview = json.dumps(raw_in, default=str)[:600] if raw_in is not None else "None"
            print(f"  [debug] raw trace.input (first 600): {preview}")

        print(f"  [debug] raw observations ({len(payload.observations)}):")
        for obs in payload.observations:
            name = obs.get("name", "")
            has_in  = obs.get("input")  is not None
            has_out = obs.get("output") is not None
            meta    = obs.get("metadata") or {}
            meta_keys = list(meta.keys()) if isinstance(meta, dict) else []
            print(f"    name={name!r:<55} in={has_in!s:<5} out={has_out!s:<5} meta_keys={meta_keys}")


def analyse_trace(
    snapshot: TraceSnapshot,
    project_id: str,
    payload: RawTracePayload | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    if debug:
        _debug_spans(snapshot, payload)
    return {
        "project_id": project_id,
        "trace_id": snapshot.trace_id,
        "user_id": snapshot.metadata.get("user_id") or snapshot.metadata.get("userId"),
        "status": snapshot.status,
        "page_name": _extract_page_name(snapshot),
        "input_screenshot": _extract_input_screenshot(snapshot, payload),
        "output_screenshot": _extract_output_screenshot(snapshot, payload),
    }


# ---------------------------------------------------------------------------
# HTML report generation
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Visual Report — {title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: #0f1117; color: #e2e8f0; padding: 24px; }}
  h1   {{ font-size: 1.4rem; font-weight: 600; margin-bottom: 4px; color: #f8fafc; }}
  .meta {{ font-size: 0.78rem; color: #64748b; margin-bottom: 32px; }}
  .grid {{ display: flex; flex-direction: column; gap: 24px; }}
  .card {{ background: #1e2433; border: 1px solid #2d3748; border-radius: 12px;
           overflow: hidden; width: 100%; }}
  .card-header {{ padding: 14px 18px; border-bottom: 1px solid #2d3748; }}
  .page-name {{ font-size: 1rem; font-weight: 600; color: #f1f5f9; }}
  .ids {{ padding: 8px 18px; font-size: 0.72rem; color: #94a3b8;
          border-bottom: 1px solid #2d3748; display: flex; gap: 24px; }}
  .ids span {{ font-family: monospace; color: #cbd5e1; }}
  .images {{ display: grid; grid-template-columns: 1fr 1fr; }}
  .img-panel {{ padding: 16px; }}
  .img-panel + .img-panel {{ border-left: 1px solid #2d3748; }}
  .img-label {{ font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
                letter-spacing: .06em; color: #64748b; margin-bottom: 10px; }}
  .img-panel img {{ width: 100%; border-radius: 6px; border: 1px solid #2d3748;
                    display: block; background: #0f1117; }}
  .no-img {{ display: flex; align-items: center; justify-content: center;
             height: 180px; background: #151b28; border-radius: 6px;
             border: 1px dashed #2d3748; color: #334155; font-size: 0.8rem; }}
</style>
</head>
<body>
<h1>Visual Report</h1>
<div class="meta">Generated {generated_at} &nbsp;·&nbsp; {count} trace(s)</div>
<div class="grid">
{cards}
</div>
</body>
</html>
"""

_CARD_TEMPLATE = """\
<div class="card">
  <div class="card-header">
    <span class="page-name">{page_name}</span>
  </div>
  <div class="ids">
    <div>Project&nbsp;<span>{project_id}</span></div>
    <div>Trace&nbsp;<span>{trace_id}</span></div>
    {user_id_html}
  </div>
  <div class="images">
    <div class="img-panel">
      <div class="img-label">Input — Figma Design</div>
      {input_img}
    </div>
    <div class="img-panel">
      <div class="img-label">Output — Generated Preview</div>
      {output_img}
    </div>
  </div>
</div>"""


def _img_tag(data_uri: str | None) -> str:
    if data_uri:
        return f'<img src="{data_uri}" alt="screenshot" loading="lazy">'
    return '<div class="no-img">not found</div>'


def generate_html(results: list[dict], title: str) -> str:
    cards = []
    for r in results:
        page = html.escape(r["page_name"] or "Unknown Page")
        uid = r.get("user_id")
        user_id_html = f'<div>User&nbsp;<span>{html.escape(uid)}</span></div>' if uid else ""
        cards.append(_CARD_TEMPLATE.format(
            page_name=page,
            project_id=html.escape(r["project_id"]),
            trace_id=html.escape(r["trace_id"]),
            user_id_html=user_id_html,
            input_img=_img_tag(r["input_screenshot"]),
            output_img=_img_tag(r["output_screenshot"]),
        ))

    return _HTML_TEMPLATE.format(
        title=html.escape(title),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        count=len(results),
        cards="\n".join(cards),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a visual side-by-side comparison report for WM agent traces.",
        epilog=(
            "Examples:\n"
            "  uv run visual-report --project-id WMPRJ001 --out report.html\n"
            "  uv run visual-report --project-id WMPRJ001 --project-id WMPRJ002 --out report.html\n"
            "  uv run visual-report --project-id WMPRJ001 --limit 10 --out report.html\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project-id",
        action="append",
        metavar="WMPRJXXX",
        dest="project_ids",
        default=[],
        help="WM project ID (repeatable for multiple projects)",
    )
    parser.add_argument(
        "--trace-id",
        action="append",
        metavar="TRACE_ID",
        dest="trace_ids",
        default=[],
        help="Langfuse trace ID (repeatable, fetched directly without project lookup)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max traces to fetch per project ID (default: 5)",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default="visual_report.html",
        help="Output HTML file path (default: visual_report.html)",
    )
    parser.add_argument(
        "--user-id",
        metavar="USER_ID",
        default=None,
        help="Langfuse userId to filter traces by (only applies to --project-id lookups)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print all span names to diagnose missing screenshots",
    )
    add_langfuse_args(parser)
    args = parser.parse_args()

    if not args.project_ids and not args.trace_ids:
        parser.error("Provide at least one --project-id or --trace-id")

    init_langfuse_env(args)
    environment = get_langfuse_environment()

    results: list[dict] = []

    # Direct trace IDs — no project lookup needed
    for trace_id in args.trace_ids:
        print(f"Fetching trace {trace_id}…", end=" ", flush=True)
        try:
            fetch_result = fetch_and_normalize(trace_id)
            result = analyse_trace(fetch_result.snapshot, trace_id, payload=fetch_result.payload, debug=args.debug)
            results.append(result)
            page = result["page_name"] or "?"
            has_in = "✓" if result["input_screenshot"] else "✗"
            has_out = "✓" if result["output_screenshot"] else "✗"
            print(f"page={page}  input={has_in}  output={has_out}")
        except Exception as exc:
            print(f"FAILED — {exc}")

    for project_id in args.project_ids:
        print(f"Searching traces for {project_id}…")
        try:
            trace_ids = MetadataFilterTraceSource(
                [("projectid", project_id)],
                limit=args.limit,
                environment=environment,
                user_id=args.user_id,
            ).get_trace_ids()
        except Exception as exc:
            print(f"  Search failed: {exc}")
            continue

        if not trace_ids:
            print(f"  No traces found.")
            continue

        print(f"  Found {len(trace_ids)} trace(s).")
        for trace_id in trace_ids:
            print(f"  Fetching {trace_id}…", end=" ", flush=True)
            try:
                fetch_result = fetch_and_normalize(trace_id)
                result = analyse_trace(fetch_result.snapshot, project_id, payload=fetch_result.payload, debug=args.debug)
                results.append(result)
                page = result["page_name"] or "?"
                has_in = "✓" if result["input_screenshot"] else "✗"
                has_out = "✓" if result["output_screenshot"] else "✗"
                print(f"page={page}  input={has_in}  output={has_out}")
            except Exception as exc:
                print(f"FAILED — {exc}")

    if not results:
        print("No results to report.")
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    title = ", ".join(args.project_ids or args.trace_ids)
    out_path.write_text(generate_html(results, title), encoding="utf-8")
    print(f"\nReport written → {out_path}  ({len(results)} trace(s))")


if __name__ == "__main__":
    main()
