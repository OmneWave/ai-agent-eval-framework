from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import yaml

from wm_agents_validator.models.trace_snapshot import (
    VARIABLE_CREATE_TOOLS,
    TraceSnapshot,
    _span_base_name,
    _variable_change_path,
    extract_paths_from_input,
)
from wm_agents_validator.models.workflow_contract import WorkflowContract

# Mirrors the path conventions in models/workflow_contract.py's _PATH_CONVENTIONS --
# reversed, to recover a resource reference from an observed file path.
_PAGE_HTML_RE = re.compile(r"^src/main/webapp/pages/(?P<page>[^/]+)/(?P=page)\.html$")
_PAGE_VARIABLES_RE = re.compile(r"^src/main/webapp/pages/(?P<page>[^/]+)/(?P=page)\.variables\.json$")
_PAGE_JS_RE = re.compile(r"^src/main/webapp/pages/(?P<page>[^/]+)/(?P=page)\.js$")
_PAGE_TOKENS_PLAN_RE = re.compile(r"^src/main/webapp/pages/(?P<page>[^/]+)/(?P=page)\.tokens-plan\.json$")
_PAGE_LAYOUT_PLAN_RE = re.compile(r"^src/main/webapp/pages/(?P<page>[^/]+)/(?P=page)\.layout-plan\.json$")
_DESIGN_TOKENS_OVERRIDE_RE = re.compile(r"^src/main/webapp/design-tokens/overrides/(?P<rest>.+)\.json$")
# `_API.json` is the documented default convention; `_apiTarget.json` is the
# real filename observed for REST/Swagger-imported services (confirmed via
# contracts/binding/binding_with_widget.yaml + its trace fixture) -- both are
# recognized rather than only the documented one, to avoid leaving every
# REST-imported API unclassified.
_API_RE = re.compile(
    r"^services/(?P<name>[^/]+)/designtime/(?P=name)_(?:API(?:_REST_SERVICE|_WEBSOCKET_SERVICE)?|apiTarget)\.json$"
)
_DB_RE = re.compile(r"^services/(?P<name>[^/]+)/designtime/(?P=name)_published_dataModel\.json$")

_OP_PRIORITY = ("delete", "write", "edit")  # first match wins -- delete is most decisive


@dataclass
class GeneratedContract:
    yaml_text: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class _ResourceDraft:
    category: str  # "page_html" | "page_variable" | "page_javascript" | "design_tokens" | "api" | "javaservice" | "db"
    reference: str
    page: str | None = None
    name: str | None = None
    path: str | None = None


def _classify_path(path: str, *, prefer_javaservice: bool) -> _ResourceDraft | None:
    norm = path.lstrip("/")
    if m := _PAGE_HTML_RE.match(norm):
        page = m["page"]
        return _ResourceDraft(category="page_html", reference=f"page.{page}", page=page)
    if m := _PAGE_VARIABLES_RE.match(norm):
        page = m["page"]
        return _ResourceDraft(category="page_variable", reference=f"page.{page}.variable", page=page)
    if m := _PAGE_JS_RE.match(norm):
        page = m["page"]
        return _ResourceDraft(category="page_javascript", reference=f"page.{page}.javascript", page=page)
    if m := _PAGE_TOKENS_PLAN_RE.match(norm):
        page = m["page"]
        name = f"{page}-tokens-plan"
        return _ResourceDraft(category="design_tokens", reference=f"design_tokens.{name}", name=name, path=norm)
    if m := _PAGE_LAYOUT_PLAN_RE.match(norm):
        page = m["page"]
        name = f"{page}-layout-plan"
        return _ResourceDraft(category="design_tokens", reference=f"design_tokens.{name}", name=name, path=norm)
    if m := _DESIGN_TOKENS_OVERRIDE_RE.match(norm):
        name = _slugify_override(m["rest"])
        return _ResourceDraft(category="design_tokens", reference=f"design_tokens.{name}", name=name, path=norm)
    if m := _DB_RE.match(norm):
        name = m["name"]
        return _ResourceDraft(category="db", reference=f"db.{name}", name=name)
    if m := _API_RE.match(norm):
        name = m["name"]
        category = "javaservice" if prefer_javaservice else "api"
        return _ResourceDraft(category=category, reference=f"{category}.{name}", name=name)
    return None


def _slugify_override(rest: str) -> str:
    """``components/button/button`` -> ``components-button``; ``global/color/color.light`` ->
    ``global-color-light`` -- drop the directory segment immediately before the filename
    (it's redundant with the stem) and join what's left, dots become hyphens.
    """
    parts = rest.split("/")
    *dirs, stem = parts
    slug = "-".join(dirs[:-1] + [stem]) if dirs else stem
    return slug.replace(".", "-")


def _operation_for(ops_seen: set[str]) -> str:
    for op in _OP_PRIORITY:
        if op in ops_seen:
            return {"delete": "DELETE", "write": "CREATE", "edit": "UPDATE"}[op]
    return "UPDATE"


def _match_for_variable(snapshot: TraceSnapshot, page: str) -> dict | list:
    """``file_changes`` (see models/trace_snapshot.py) already ensures every
    ``ui_create*Variable``/``ui_updateVariable`` call surfaces as a
    ``page_variable`` output entry even with no accompanying file write --
    this only recovers the call's own arguments to build a ``match`` clause
    from, via the same path-resolution logic (``_variable_change_path``) so
    both agree on which call belongs to which page.
    """
    target_path = f"src/main/webapp/pages/{page}/{page}.variables.json"
    for span in snapshot.spans:
        if span.type != "TOOL" or _span_base_name(span.name) not in VARIABLE_CREATE_TOOLS:
            continue
        tool_input = span.input or {}
        if _variable_change_path(tool_input) != target_path:
            continue
        operation_id = tool_input.get("operationId")
        if operation_id:
            return {"operationId": operation_id}
        variable_data = tool_input.get("variableData") or {}
        name = variable_data.get("name")
        if name:
            return [name]
    return {}


def _scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if re.match(r"^[A-Za-z0-9_./-]+$", text):
        return text
    return json.dumps(text)


def _match_flow(match: dict | list) -> str | None:
    if isinstance(match, dict) and match:
        return "{" + ", ".join(f"{k}: {_scalar(v)}" for k, v in match.items()) + "}"
    if isinstance(match, list) and match:
        return "[" + ", ".join(_scalar(v) for v in match) + "]"
    return None


def _list_block(label: str, items: list[str], indent: str = "  ") -> list[str]:
    if not items:
        return [f"{indent}{label}: []"]
    lines = [f"{indent}{label}:"]
    lines.extend(f"{indent}  - {_scalar(item)}" for item in items)
    return lines


def generate_contract(
    snapshot: TraceSnapshot,
    *,
    workflow: str,
    contract_version: str = "1.0.0",
) -> GeneratedContract:
    """Reverse-engineers a starter ``WorkflowContract`` YAML from one observed trace.

    This is a bootstrapping aid, not a source of truth: it only knows what one
    trace happened to do, so ``skills``/``tools`` end up as "everything observed"
    (no required-vs-optional judgement) and every ``output`` entry is inferred
    structurally (path + operation), never checked for business-logic correctness.
    Always review the result -- especially ``match`` clauses left empty, and any
    path reported as unclassifiable in ``GeneratedContract.warnings``.
    """
    warnings: list[str] = []
    prefer_javaservice = any(
        "java-service" in name or "javaservice" in name
        for load in snapshot.skill_loads
        for name in load.skill_names
    )

    ops_by_path: dict[str, set[str]] = {}
    for fc in snapshot.file_changes:
        ops_by_path.setdefault(fc.path, set()).add(fc.operation)

    pages: set[str] = set()
    design_tokens: dict[str, str] = {}
    apis: set[str] = set()
    javaservices: set[str] = set()
    dbs: set[str] = set()
    output_entries: list[tuple[str, str, dict | list]] = []
    unclassified_writes: list[str] = []

    def _register(draft: _ResourceDraft) -> None:
        if draft.category in ("page_html", "page_variable", "page_javascript"):
            pages.add(draft.page)  # type: ignore[arg-type]
        elif draft.category == "design_tokens":
            design_tokens.setdefault(draft.name, draft.path)  # type: ignore[arg-type]
        elif draft.category == "api":
            apis.add(draft.name)  # type: ignore[arg-type]
        elif draft.category == "javaservice":
            javaservices.add(draft.name)  # type: ignore[arg-type]
        elif draft.category == "db":
            dbs.add(draft.name)  # type: ignore[arg-type]

    for path in sorted(ops_by_path):
        draft = _classify_path(path, prefer_javaservice=prefer_javaservice)
        if draft is None:
            unclassified_writes.append(path)
            continue
        _register(draft)
        operation = _operation_for(ops_by_path[path])
        match: dict | list = _match_for_variable(snapshot, draft.page) if draft.category == "page_variable" else {}
        output_entries.append((draft.reference, operation, match))

    if unclassified_writes:
        warnings.append(
            "Could not classify these written/edited paths into a resource type -- "
            f"add them to `output` by hand if they matter: {unclassified_writes}"
        )

    # Note: ui_create*Variable/ui_updateVariable calls with no accompanying file
    # write are already covered above -- TraceSnapshot.file_changes synthesizes
    # a FileChangeRecord for them directly, so they flow through the same
    # ops_by_path loop as any other write.

    output_refs = {ref for ref, _, _ in output_entries}
    input_entries: list[str] = []
    seen_input_refs: set[str] = set()
    unclassified_reads: list[str] = []
    for span in snapshot.spans:
        if span.type != "TOOL" or _span_base_name(span.name) != "read_files":
            continue
        for path in extract_paths_from_input(span.input or {}, "read_files"):
            draft = _classify_path(path, prefer_javaservice=prefer_javaservice)
            if draft is None:
                if path not in unclassified_reads:
                    unclassified_reads.append(path)
                continue
            ref = draft.reference
            if draft.category == "page_variable":
                ref = f"page.{draft.page}"  # input_context has no `.variable` content-check use case
            if ref in output_refs or ref in seen_input_refs:
                continue
            seen_input_refs.add(ref)
            input_entries.append(ref)
            _register(draft)

    if unclassified_reads:
        warnings.append(
            f"Could not classify these read paths into a resource type -- add manually if meaningful: {unclassified_reads}"
        )

    skills: list[str] = []
    for load in snapshot.skill_loads:
        for name in load.skill_names:
            if name not in skills:
                skills.append(name)
    if not skills:
        warnings.append("No skill_loads observed in this trace -- `skills.required` is empty; fill in manually.")

    if not output_entries:
        warnings.append("No file writes/edits observed in this trace -- `output` is empty; this contract can't verify much.")

    tools_required = sorted(snapshot.tools_summary.called)

    yaml_text = _render_yaml(
        workflow=workflow,
        contract_version=contract_version,
        skills=skills,
        pages=sorted(pages),
        design_tokens=design_tokens,
        apis=sorted(apis),
        javaservices=sorted(javaservices),
        dbs=sorted(dbs),
        input_entries=input_entries,
        output_entries=output_entries,
        tools_required=tools_required,
    )

    _self_check(yaml_text)

    return GeneratedContract(yaml_text=yaml_text, warnings=warnings)


def _render_yaml(
    *,
    workflow: str,
    contract_version: str,
    skills: list[str],
    pages: list[str],
    design_tokens: dict[str, str],
    apis: list[str],
    javaservices: list[str],
    dbs: list[str],
    input_entries: list[str],
    output_entries: list[tuple[str, str, dict | list]],
    tools_required: list[str],
) -> str:
    lines: list[str] = []
    lines.append(f"workflow: {_scalar(workflow)}")
    lines.append(f'contract_version: "{contract_version}"')
    lines.append("skills:")
    lines.extend(_list_block("required", skills))
    lines.extend(_list_block("optional", []))
    lines.append("")
    lines.append("knowledge: []")
    lines.append("")
    lines.append("resources:")
    has_resources = bool(pages or design_tokens or apis or javaservices or dbs)
    if not has_resources:
        lines[-1] = "resources: {}"
    else:
        if pages:
            lines.append("  page:")
            lines.extend(f"    - name: {_scalar(name)}" for name in pages)
        if design_tokens:
            lines.append("  design_tokens:")
            for name in sorted(design_tokens):
                lines.append(f"    - name: {_scalar(name)}")
                lines.append(f"      path: {_scalar(design_tokens[name])}")
        if apis:
            lines.append("  api:")
            lines.extend(f"    - name: {_scalar(name)}" for name in apis)
        if javaservices:
            lines.append("  javaservice:")
            lines.extend(f"    - name: {_scalar(name)}" for name in javaservices)
        if dbs:
            lines.append("  db:")
            lines.extend(f"    - name: {_scalar(name)}" for name in dbs)
    lines.append("")

    lines.append("input_context:")
    if not input_entries:
        lines[-1] = "input_context: []"
    else:
        lines.extend(f"  - resource: {_scalar(ref)}" for ref in input_entries)
    lines.append("")

    lines.append("output:")
    if not output_entries:
        lines[-1] = "output: []"
    else:
        for ref, operation, match in output_entries:
            lines.append(f"  - resource: {_scalar(ref)}")
            lines.append(f"    operation: {operation}")
            match_repr = _match_flow(match)
            if match_repr is not None:
                lines.append(f"    match: {match_repr}")
    lines.append("")

    lines.append("tools:")
    lines.extend(_list_block("required", tools_required))
    lines.extend(_list_block("optional", []))
    lines.extend(_list_block("forbidden", []))
    lines.append("")

    return "\n".join(lines)


def _self_check(yaml_text: str) -> None:
    """A generator that silently emits invalid YAML/contract is worse than none --
    fail loudly here instead of leaving the bug for the user to discover later."""
    data = yaml.safe_load(yaml_text)
    contract = WorkflowContract.model_validate(data)
    for entry in contract.input_context:
        contract.resources.resolve(entry.resource)
    for entry in contract.output:
        contract.resources.resolve(entry.resource)
