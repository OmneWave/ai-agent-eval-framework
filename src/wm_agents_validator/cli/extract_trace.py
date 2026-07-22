"""
extract-trace: Analyse write_file / edit_file_content tool calls from agent traces.

For each trace (looked up by projectId or traceId) it reports:
  - HTML pages       → WM element types, their attributes and variant→attribute mappings
  - Design tokens    → token file categories, nested variants and their properties
  - Variable files   → variable names and types (via write_file AND platform tool calls)

Supports batch mode: pass multiple --project-id values to aggregate results from
up to 30 projects in a single report.

Usage:
  uv run extract-trace --project-id WMPRJ001 --langfuse-environment stage-ai
  uv run extract-trace --project-id WMPRJ001 --project-id WMPRJ002
  uv run extract-trace --trace-id abc123def456
  uv run extract-trace --project-id WMPRJ001 --out report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from wm_agents_validator.cli.langfuse_config import (
    add_langfuse_args,
    get_langfuse_environment,
    init_langfuse_env,
)
from wm_agents_validator.comparison.sources import MetadataFilterTraceSource
from wm_agents_validator.controller.fetch import fetch_and_normalize
from wm_agents_validator.models.trace_snapshot import (
    FILE_WRITE_TOOLS,
    VARIABLE_CREATE_TOOLS,
    SpanRecord,
    TraceSnapshot,
)

console = Console()

# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------

def _base_tool_name(span_name: str) -> str:
    """'write_file (abc123)' → 'write_file'"""
    return span_name.split("(")[0].strip()


def _file_write_spans(snapshot: TraceSnapshot) -> list[SpanRecord]:
    return [
        s for s in snapshot.spans
        if s.type == "TOOL"
        and _base_tool_name(s.name) in FILE_WRITE_TOOLS
        and s.input
    ]


def _variable_tool_spans(snapshot: TraceSnapshot) -> list[SpanRecord]:
    return [
        s for s in snapshot.spans
        if s.type == "TOOL"
        and _base_tool_name(s.name) in VARIABLE_CREATE_TOOLS
        and s.input
    ]


def _get_file_content(span: SpanRecord) -> str:
    """Extract written content from write_file or edit_file_content span input."""
    inp = span.input or {}
    return inp.get("file_content") or inp.get("content") or inp.get("new_content") or ""


# ---------------------------------------------------------------------------
# HTML element parser
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r'<(wm-[a-z][a-z0-9-]*)\s*((?:[^">/]|"[^"]*")*)\s*/?>', re.DOTALL)
_ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
_SKIP_ATTRS = frozenset({"name"})  # instance-specific names add noise


def parse_html_elements(content: str) -> dict[str, Any]:
    """
    Returns:
      {
        "wm-label": {
          "count": 8,
          "attributes": {"caption": ["Welcome", "Balance"], "variant": ["brand", "default"]},
          "variants": {"brand": ["caption", "class"], "default": ["caption"]}
        }
      }
    """
    elements: dict[str, dict] = defaultdict(lambda: {
        "count": 0,
        "attributes": defaultdict(set),
        "variants": defaultdict(set),
    })

    for m in _TAG_RE.finditer(content):
        tag = m.group(1)
        attrs = dict(_ATTR_RE.findall(m.group(2)))
        el = elements[tag]
        el["count"] += 1
        variant = attrs.get("variant")
        for k, v in attrs.items():
            if k in _SKIP_ATTRS:
                continue
            el["attributes"][k].add(v)
            if variant:
                el["variants"][variant].add(k)

    return {
        tag: {
            "count": data["count"],
            "attributes": {k: sorted(v) for k, v in data["attributes"].items()},
            "variants": {v: sorted(a) for v, a in data["variants"].items()},
        }
        for tag, data in elements.items()
    }


def _merge_html_elements(base: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge incoming element data into base in-place."""
    for tag, data in incoming.items():
        if tag not in base:
            base[tag] = data
        else:
            base[tag]["count"] += data["count"]
            for attr, vals in data["attributes"].items():
                base[tag]["attributes"][attr] = sorted(
                    set(base[tag]["attributes"].get(attr, [])) | set(vals)
                )
            for variant, attrs in data["variants"].items():
                base[tag]["variants"][variant] = sorted(
                    set(base[tag]["variants"].get(variant, [])) | set(attrs)
                )


# ---------------------------------------------------------------------------
# Design token parser
# ---------------------------------------------------------------------------

def parse_design_tokens(content: str, file_path: str) -> dict[str, Any]:
    """
    Returns:
      {
        "file": "components/btn/btn.json",
        "variants": {"default": ["bg", "color"], "primary": ["bg", "color"]},
        "flat_keys": ["brand-primary", ...]   # only for non-nested token files
      }
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {"file": file_path, "error": "invalid JSON"}

    nested = {k: v for k, v in data.items() if isinstance(v, dict)}
    flat = [k for k, v in data.items() if not isinstance(v, dict)]

    result: dict[str, Any] = {"file": file_path}
    if nested:
        result["variants"] = {k: sorted(v.keys()) for k, v in nested.items()}
    if flat:
        result["flat_keys"] = sorted(flat)
    return result


# ---------------------------------------------------------------------------
# Variable parsers
# ---------------------------------------------------------------------------

def parse_variable_file(content: str) -> list[dict[str, Any]]:
    """Parse a *.variables.json file → [{name, type, isList}]."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []

    root = data.get("Variables") or data.get("variables") or data
    if not isinstance(root, dict):
        return []

    return [
        {
            "name": name,
            "type": spec.get("type", "unknown") if isinstance(spec, dict) else "unknown",
            "isList": spec.get("isList", False) if isinstance(spec, dict) else False,
            "source": "write_file",
        }
        for name, spec in root.items()
    ]


def parse_variable_tool_span(span: SpanRecord) -> dict[str, Any] | None:
    if not span.input:
        return None
    return {
        "name": span.input.get("name", "?"),
        "type": _base_tool_name(span.name),
        "isList": span.input.get("isList", False),
        "source": "tool_call",
    }


# ---------------------------------------------------------------------------
# Trace analyser
# ---------------------------------------------------------------------------

_HTML_PATH_RE = re.compile(r'pages/[^/]+/[^/]+\.html$')
_TOKEN_PATH_RE = re.compile(r'design-tokens/')
_VAR_PATH_RE = re.compile(r'\.variables\.json$|/variables\.json$')


def analyse_trace(snapshot: TraceSnapshot) -> dict[str, Any]:
    """Return structured analysis of a single TraceSnapshot."""
    html_elements: dict[str, Any] = {}
    design_tokens: list[dict] = []
    variables: list[dict] = []
    other_files: list[str] = []

    for span in _file_write_spans(snapshot):
        file_path: str = (span.input or {}).get("file_path", "")
        content: str = _get_file_content(span)

        if _HTML_PATH_RE.search(file_path):
            _merge_html_elements(html_elements, parse_html_elements(content))
        elif _TOKEN_PATH_RE.search(file_path):
            design_tokens.append(parse_design_tokens(content, file_path))
        elif _VAR_PATH_RE.search(file_path):
            variables.extend(parse_variable_file(content))
        else:
            other_files.append(file_path)

    for span in _variable_tool_spans(snapshot):
        info = parse_variable_tool_span(span)
        if info:
            variables.append(info)

    # Deduplicate variables by name (tool call + write_file may both appear)
    seen: set[str] = set()
    unique_vars = []
    for v in variables:
        if v["name"] not in seen:
            seen.add(v["name"])
            unique_vars.append(v)

    return {
        "trace_id": snapshot.trace_id,
        "status": snapshot.status,
        "html_elements": html_elements,
        "design_tokens": design_tokens,
        "variables": unique_vars,
        "other_files": other_files,
    }


# ---------------------------------------------------------------------------
# Rich display helpers
# ---------------------------------------------------------------------------

def _display_project(project_id: str, trace_id: str, analysis: dict) -> None:
    console.print(Rule(
        f"[bold cyan]{project_id}[/]  [dim]trace: {trace_id[:20]}…[/]",
        style="cyan",
    ))

    if analysis["html_elements"]:
        t = Table(title="HTML Elements", box=box.SIMPLE_HEAVY, show_lines=True, expand=False)
        t.add_column("Element", style="bold yellow", no_wrap=True)
        t.add_column("Count", justify="right")
        t.add_column("Attributes", overflow="fold")
        t.add_column("Variants → Attributes", overflow="fold")
        for tag, data in sorted(analysis["html_elements"].items()):
            attrs_str = ", ".join(sorted(data["attributes"]))
            variants_str = "\n".join(
                f"[green]{v}[/]: {', '.join(a)}"
                for v, a in sorted(data["variants"].items())
            ) or "—"
            t.add_row(tag, str(data["count"]), attrs_str, variants_str)
        console.print(t)

    if analysis["design_tokens"]:
        t = Table(title="Design Tokens", box=box.SIMPLE_HEAVY, show_lines=True, expand=False)
        t.add_column("File", style="bold magenta", no_wrap=True)
        t.add_column("Variants / Keys", overflow="fold")
        for tok in analysis["design_tokens"]:
            label = Path(tok.get("file", "?")).name
            if "error" in tok:
                detail = f"[red]{tok['error']}[/]"
            elif "variants" in tok:
                detail = "\n".join(
                    f"[green]{v}[/]: {', '.join(props)}"
                    for v, props in sorted(tok["variants"].items())
                )
                if "flat_keys" in tok:
                    detail += "\n" + ", ".join(tok["flat_keys"])
            else:
                detail = ", ".join(tok.get("flat_keys", []))
            t.add_row(label, detail)
        console.print(t)

    if analysis["variables"]:
        t = Table(title="Variables", box=box.SIMPLE_HEAVY, expand=False)
        t.add_column("Name", style="bold green")
        t.add_column("Type")
        t.add_column("List?")
        t.add_column("Source", style="dim")
        for v in analysis["variables"]:
            t.add_row(v["name"], v.get("type", "?"), str(v.get("isList", False)), v.get("source", "?"))
        console.print(t)

    if not any([analysis["html_elements"], analysis["design_tokens"], analysis["variables"]]):
        console.print("[yellow]  No write_file output found in this trace.[/]\n")


def _display_aggregate(results: list[dict]) -> None:
    console.print(Rule(f"[bold white]AGGREGATE — {len(results)} trace(s)[/]", style="white"))

    # Merge HTML elements across all results
    merged_elements: dict[str, dict] = {}
    for r in results:
        _merge_html_elements(merged_elements, r["analysis"]["html_elements"])

    if merged_elements:
        t = Table(
            title=f"All Elements across {len(results)} project(s)",
            box=box.SIMPLE_HEAVY, show_lines=True, expand=False,
        )
        t.add_column("Element", style="bold yellow", no_wrap=True)
        t.add_column("Total", justify="right")
        t.add_column("All Attributes", overflow="fold")
        t.add_column("All Variants → Attributes", overflow="fold")
        for tag, data in sorted(merged_elements.items()):
            attrs_str = ", ".join(sorted(data["attributes"]))
            variants_str = "\n".join(
                f"[green]{v}[/]: {', '.join(a)}"
                for v, a in sorted(data["variants"].items())
            ) or "—"
            t.add_row(tag, str(data["count"]), attrs_str, variants_str)
        console.print(t)

    # Aggregate token files
    token_files: dict[str, set] = defaultdict(set)
    for r in results:
        for tok in r["analysis"]["design_tokens"]:
            fname = Path(tok.get("file", "?")).name
            for v in tok.get("variants", {}).keys():
                token_files[fname].add(v)

    if token_files:
        t = Table(title="Design Token Files Seen", box=box.SIMPLE_HEAVY, expand=False)
        t.add_column("File", style="bold magenta")
        t.add_column("Variants observed")
        for fname, variants in sorted(token_files.items()):
            t.add_row(fname, ", ".join(sorted(variants)) or "—")
        console.print(t)

    # Aggregate variables
    all_vars: dict[str, set] = defaultdict(set)
    for r in results:
        for v in r["analysis"]["variables"]:
            all_vars[v["name"]].add(v.get("type", "?"))

    if all_vars:
        t = Table(title="All Variables Seen", box=box.SIMPLE_HEAVY, expand=False)
        t.add_column("Name", style="bold green")
        t.add_column("Types observed")
        for name, types in sorted(all_vars.items()):
            t.add_row(name, ", ".join(sorted(types)))
        console.print(t)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse write_file/edit_file_content tool calls across agent traces.",
        epilog=(
            "Examples:\n"
            "  uv run extract-trace --project-id WMPRJ001 --langfuse-environment stage-ai\n"
            "  uv run extract-trace --project-id WMPRJ001 --project-id WMPRJ002\n"
            "  uv run extract-trace --trace-id abc123def456\n"
            "  uv run extract-trace --project-id WMPRJ001 --out report.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project-id",
        action="append",
        metavar="WMPRJXXX",
        dest="project_ids",
        help="WM project ID to analyse (repeatable for batch, up to 30)",
    )
    parser.add_argument(
        "--trace-id",
        action="append",
        metavar="TRACE_ID",
        dest="trace_ids",
        help="Langfuse trace ID to analyse directly (repeatable)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Max traces to fetch per project ID (default: 1 = most recent)",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="Write full analysis as JSON to this path",
    )
    add_langfuse_args(parser)
    args = parser.parse_args()

    if not args.project_ids and not args.trace_ids:
        parser.error("Provide at least one --project-id or --trace-id")

    init_langfuse_env(args)
    environment = get_langfuse_environment()

    results: list[dict] = []

    for project_id in (args.project_ids or []):
        console.print(f"[dim]Searching traces for {project_id}…[/]")
        try:
            trace_ids = MetadataFilterTraceSource(
                [("projectid", project_id)],
                limit=args.limit,
                environment=environment,
            ).get_trace_ids()
        except Exception as exc:
            console.print(f"[red]  Search failed for {project_id}: {exc}[/]")
            continue

        if not trace_ids:
            console.print(f"[yellow]  No traces found for {project_id}[/]")
            continue

        for trace_id in trace_ids:
            console.print(f"[dim]  Fetching {trace_id}…[/]")
            try:
                snapshot = fetch_and_normalize(trace_id).snapshot
                results.append({
                    "project_id": project_id,
                    "trace_id": trace_id,
                    "analysis": analyse_trace(snapshot),
                })
            except Exception as exc:
                console.print(f"[red]  Failed to fetch {trace_id}: {exc}[/]")

    for trace_id in (args.trace_ids or []):
        console.print(f"[dim]Fetching {trace_id}…[/]")
        try:
            snapshot = fetch_and_normalize(trace_id).snapshot
            results.append({
                "project_id": "—",
                "trace_id": trace_id,
                "analysis": analyse_trace(snapshot),
            })
        except Exception as exc:
            console.print(f"[red]  Failed to fetch {trace_id}: {exc}[/]")

    if not results:
        console.print("[red]No traces could be analysed.[/]")
        sys.exit(1)

    console.print()
    for r in results:
        _display_project(r["project_id"], r["trace_id"], r["analysis"])

    if len(results) > 1:
        _display_aggregate(results)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(results, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(f"\n[green]Full analysis written → {out_path}[/]")


if __name__ == "__main__":
    main()
