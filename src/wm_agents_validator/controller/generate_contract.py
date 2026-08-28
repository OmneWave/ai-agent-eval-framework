from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import yaml

from wm_agents_validator.models.trace_snapshot import (
    VARIABLE_CREATE_TOOLS,
    DELEGATION_TOOL_NAMES,
    SKILL_TOOL,
    FILE_WRITE_TOOLS,
    TraceSnapshot,
    _span_base_name,
    _variable_change_path,
    extract_paths_from_input,
    unwrap_execute_tool,
)
from wm_agents_validator.models.workflow_contract import WorkflowContract

_OP_PRIORITY = ("delete", "write", "edit")  # first match wins -- delete is most decisive

# Generic, non-WaveMaker-specific CRUD-verb heuristic used to spot a mutation-shaped
# tool call that has no discoverable file path at all (e.g. an "apply changes to
# this markup" style call) -- these become `ToolCheck` (`tool:`+`match:`) output
# entries instead of only being listed flatly in `tools.required`.
_MUTATION_VERBS = (
    "create",
    "update",
    "delete",
    "write",
    "edit",
    "apply",
    "remove",
    "add",
    "set",
    "publish",
    "save",
    "generate",
    "modify",
)

# Fields checked, in priority order, when deriving a `match` clause from a tool
# call's own structured input -- generic across tool shapes, not WaveMaker-specific.
_MATCH_FIELD_PRIORITY = ("operationId", "id", "name", "pageName")


@dataclass
class GeneratedContract:
    yaml_text: str
    warnings: list[str] = field(default_factory=list)


class ContractGenerator(ABC):
    """Strategy interface for "reverse-engineer a starter contract from one
    observed trace" -- see ``WaveMakerContractGenerator`` for the concrete,
    WaveMaker-project-convention implementation. A different resource
    vocabulary (a different platform's file-layout/tool-naming conventions)
    gets its own implementation of this interface rather than new branches
    bolted onto the WaveMaker one.
    """

    @abstractmethod
    def generate(
        self,
        snapshot: TraceSnapshot,
        *,
        workflow: str,
        contract_version: str = "1.0.0",
    ) -> GeneratedContract: ...


def _build_match(tool_input: dict) -> dict | list:
    """Derive a ``match`` clause from a tool call's own structured input --
    generic across tool shapes: prefer a handful of common identifying
    top-level fields, then fall back to any nested object carrying a
    ``name``. Used both for page-variable ``WriteSpec.match`` and for the
    ``ToolCheck`` entries ``WaveMakerContractGenerator`` emits for mutation
    calls that have no discoverable file path.
    """
    for key in _MATCH_FIELD_PRIORITY:
        value = tool_input.get(key)
        if value:
            return {key: value}
    for value in tool_input.values():
        if isinstance(value, dict) and value.get("name"):
            return {"name": value["name"]}
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


@dataclass
class _PageDraft:
    path: str | None = None
    variable: dict[str, str] = field(default_factory=dict)  # name -> path
    javascript: dict[str, str] = field(default_factory=dict)  # name -> path


@dataclass
class _ResourceDraft:
    category: str  # "page_html" | "page_variable" | "page_javascript" | "design_tokens" | "api" | "javaservice" | "db"
    reference: str
    page: str | None = None
    name: str | None = None
    path: str | None = None


@dataclass
class _ToolCheckEntry:
    tool: str
    match: dict | list


class WaveMakerContractGenerator(ContractGenerator):
    """Reverse-engineers a starter ``WorkflowContract`` YAML from one observed
    trace, using WaveMaker's own project-file conventions (page/api/javaservice/db
    path layout) to recognize resources.

    This is a bootstrapping aid, not a source of truth: it only knows what one
    trace happened to do, so ``skills``/``tools`` end up as "everything observed"
    (no required-vs-optional judgement) and every ``output`` entry is inferred
    structurally (path + operation, or tool + match), never checked for
    business-logic correctness. Always review the result -- especially ``match``
    clauses left empty, and any path reported as unclassifiable in
    ``GeneratedContract.warnings``.
    """

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

    def _classify_path(self, path: str, *, prefer_javaservice: bool) -> _ResourceDraft | None:
        norm = path.lstrip("/")
        if m := self._PAGE_HTML_RE.match(norm):
            page = m["page"]
            return _ResourceDraft(category="page_html", reference=f"page.{page}", page=page, path=norm)
        if m := self._PAGE_VARIABLES_RE.match(norm):
            page = m["page"]
            return _ResourceDraft(category="page_variable", reference=f"page.{page}.variable", page=page, path=norm)
        if m := self._PAGE_JS_RE.match(norm):
            page = m["page"]
            return _ResourceDraft(category="page_javascript", reference=f"page.{page}.javascript", page=page, path=norm)
        if m := self._PAGE_TOKENS_PLAN_RE.match(norm):
            page = m["page"]
            name = f"{page}-tokens-plan"
            return _ResourceDraft(category="design_tokens", reference=f"design_tokens.{name}", name=name, path=norm)
        if m := self._PAGE_LAYOUT_PLAN_RE.match(norm):
            page = m["page"]
            name = f"{page}-layout-plan"
            return _ResourceDraft(category="design_tokens", reference=f"design_tokens.{name}", name=name, path=norm)
        if m := self._DESIGN_TOKENS_OVERRIDE_RE.match(norm):
            name = self._slugify_override(m["rest"])
            return _ResourceDraft(category="design_tokens", reference=f"design_tokens.{name}", name=name, path=norm)
        if m := self._DB_RE.match(norm):
            name = m["name"]
            return _ResourceDraft(category="db", reference=f"db.{name}", name=name, path=norm)
        if m := self._API_RE.match(norm):
            name = m["name"]
            category = "javaservice" if prefer_javaservice else "api"
            return _ResourceDraft(category=category, reference=f"{category}.{name}", name=name, path=norm)
        return None

    @staticmethod
    def _slugify_override(rest: str) -> str:
        """``components/button/button`` -> ``components-button``; ``global/color/color.light`` ->
        ``global-color-light`` -- drop the directory segment immediately before the filename
        (it's redundant with the stem) and join what's left, dots become hyphens.
        """
        parts = rest.split("/")
        *dirs, stem = parts
        slug = "-".join(dirs[:-1] + [stem]) if dirs else stem
        return slug.replace(".", "-")

    @staticmethod
    def _operation_for(ops_seen: set[str]) -> str:
        for op in _OP_PRIORITY:
            if op in ops_seen:
                return {"delete": "DELETE", "write": "CREATE", "edit": "UPDATE"}[op]
        return "UPDATE"

    @staticmethod
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
            return _build_match(tool_input)
        return {}

    @staticmethod
    def _variable_name_for(snapshot: TraceSnapshot, page: str) -> str | None:
        target_path = f"src/main/webapp/pages/{page}/{page}.variables.json"
        for span in snapshot.spans:
            if span.type != "TOOL" or _span_base_name(span.name) not in VARIABLE_CREATE_TOOLS:
                continue
            tool_input = span.input or {}
            if _variable_change_path(tool_input) != target_path:
                continue
            operation_id = tool_input.get("operationId")
            if operation_id:
                return str(operation_id)
            variable_data = tool_input.get("variableData") or {}
            name = variable_data.get("name")
            if name:
                return str(name)
        return None

    def _tool_check_entries(self, snapshot: TraceSnapshot) -> list[_ToolCheckEntry]:
        """Mutation-shaped tool calls with no discoverable file path (e.g. an
        "apply changes to this markup" style call) can't become a path-based
        ``WriteSpec`` -- instead of only showing up in the flat
        ``tools.required`` bag, they become standalone ``ToolCheck`` entries
        (``tool:``+``match:``), the same mechanism hand-written contracts
        already use (see ``docs/CONTRACT_SPEC.md``'s ``PetTable`` example).
        """
        entries: list[_ToolCheckEntry] = []
        seen: set[tuple[str, str]] = set()
        excluded = FILE_WRITE_TOOLS | VARIABLE_CREATE_TOOLS | DELEGATION_TOOL_NAMES | {SKILL_TOOL, "read_files"}
        for span in snapshot.spans:
            if span.type != "TOOL":
                continue
            raw_base = _span_base_name(span.name)
            base_name, tool_input = unwrap_execute_tool(raw_base, span.input or {})
            if base_name in excluded:
                continue
            if not any(verb in base_name.lower() for verb in _MUTATION_VERBS):
                continue
            dotted = f"{raw_base}.{base_name}" if base_name != raw_base else base_name
            match = _build_match(tool_input)
            key = (dotted, json.dumps(match, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            entries.append(_ToolCheckEntry(tool=dotted, match=match))
        return entries

    def generate(
        self,
        snapshot: TraceSnapshot,
        *,
        workflow: str,
        contract_version: str = "1.0.0",
    ) -> GeneratedContract:
        warnings: list[str] = []
        prefer_javaservice = any(
            "java-service" in name or "javaservice" in name
            for load in snapshot.skill_loads
            for name in load.skill_names
        )

        ops_by_path: dict[str, set[str]] = {}
        for fc in snapshot.file_changes:
            ops_by_path.setdefault(fc.path, set()).add(fc.operation)

        pages: dict[str, _PageDraft] = {}
        design_tokens: dict[str, str] = {}
        apis: dict[str, str] = {}
        javaservices: dict[str, str] = {}
        dbs: dict[str, str] = {}
        output_entries: list[tuple[str, str, dict | list]] = []
        unclassified_writes: list[str] = []

        def _register(draft: _ResourceDraft) -> str:
            """Registers ``draft`` and returns the *fully-qualified* resource
            reference for it -- for nested page sub-resources this is deeper
            than ``draft.reference`` (which only names the sub-type, not the
            specific sub-entry), since the sub-entry's own name isn't known
            until registration time (e.g. a variable's name comes from its
            evidencing tool call, not from the file path alone).
            """
            if draft.category == "page_html":
                pages.setdefault(draft.page, _PageDraft()).path = draft.path
                return draft.reference
            if draft.category == "page_variable":
                page_draft = pages.setdefault(draft.page, _PageDraft())
                name = self._variable_name_for(snapshot, draft.page) or draft.page
                page_draft.variable.setdefault(name, draft.path)
                return f"{draft.reference}.{name}"
            if draft.category == "page_javascript":
                page_draft = pages.setdefault(draft.page, _PageDraft())
                page_draft.javascript.setdefault(draft.page, draft.path)
                return f"{draft.reference}.{draft.page}"
            if draft.category == "design_tokens":
                design_tokens.setdefault(draft.name, draft.path)
            elif draft.category == "api":
                apis.setdefault(draft.name, draft.path)
            elif draft.category == "javaservice":
                javaservices.setdefault(draft.name, draft.path)
            elif draft.category == "db":
                dbs.setdefault(draft.name, draft.path)
            return draft.reference

        for path in sorted(ops_by_path):
            draft = self._classify_path(path, prefer_javaservice=prefer_javaservice)
            if draft is None:
                unclassified_writes.append(path)
                continue
            full_ref = _register(draft)
            operation = self._operation_for(ops_by_path[path])
            match: dict | list = (
                self._match_for_variable(snapshot, draft.page) if draft.category == "page_variable" else {}
            )
            output_entries.append((full_ref, operation, match))

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
                draft = self._classify_path(path, prefer_javaservice=prefer_javaservice)
                if draft is None:
                    if path not in unclassified_reads:
                        unclassified_reads.append(path)
                    continue
                if draft.category == "page_variable":
                    ref = f"page.{draft.page}"  # input_context has no `.variable` content-check use case
                    _register(draft)
                else:
                    ref = _register(draft)
                if ref in output_refs or ref in seen_input_refs:
                    continue
                seen_input_refs.add(ref)
                input_entries.append(ref)

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

        tool_check_entries = self._tool_check_entries(snapshot)

        if not output_entries and not tool_check_entries:
            warnings.append("No file writes/edits observed in this trace -- `output` is empty; this contract can't verify much.")

        tools_required = sorted(snapshot.tools_summary.called)

        yaml_text = _render_yaml(
            workflow=workflow,
            contract_version=contract_version,
            skills=skills,
            pages=pages,
            design_tokens=design_tokens,
            apis=apis,
            javaservices=javaservices,
            dbs=dbs,
            input_entries=input_entries,
            output_entries=output_entries,
            tool_check_entries=tool_check_entries,
            tools_required=tools_required,
        )

        _self_check(yaml_text)

        return GeneratedContract(yaml_text=yaml_text, warnings=warnings)


def _render_yaml(
    *,
    workflow: str,
    contract_version: str,
    skills: list[str],
    pages: dict[str, _PageDraft],
    design_tokens: dict[str, str],
    apis: dict[str, str],
    javaservices: dict[str, str],
    dbs: dict[str, str],
    input_entries: list[str],
    output_entries: list[tuple[str, str, dict | list]],
    tool_check_entries: list[_ToolCheckEntry],
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
            for name in sorted(pages):
                page_draft = pages[name]
                lines.append(f"    - name: {_scalar(name)}")
                if page_draft.path:
                    lines.append(f"      path: {_scalar(page_draft.path)}")
                if page_draft.variable:
                    lines.append("      variable:")
                    for var_name in sorted(page_draft.variable):
                        lines.append(f"        - name: {_scalar(var_name)}")
                        lines.append(f"          path: {_scalar(page_draft.variable[var_name])}")
                if page_draft.javascript:
                    lines.append("      javascript:")
                    for js_name in sorted(page_draft.javascript):
                        lines.append(f"        - name: {_scalar(js_name)}")
                        lines.append(f"          path: {_scalar(page_draft.javascript[js_name])}")
        if design_tokens:
            lines.append("  design_tokens:")
            for name in sorted(design_tokens):
                lines.append(f"    - name: {_scalar(name)}")
                lines.append(f"      path: {_scalar(design_tokens[name])}")
        if apis:
            lines.append("  api:")
            for name in sorted(apis):
                lines.append(f"    - name: {_scalar(name)}")
                lines.append(f"      path: {_scalar(apis[name])}")
        if javaservices:
            lines.append("  javaservice:")
            for name in sorted(javaservices):
                lines.append(f"    - name: {_scalar(name)}")
                lines.append(f"      path: {_scalar(javaservices[name])}")
        if dbs:
            lines.append("  db:")
            for name in sorted(dbs):
                lines.append(f"    - name: {_scalar(name)}")
                lines.append(f"      path: {_scalar(dbs[name])}")
    lines.append("")

    lines.append("input_context:")
    if not input_entries:
        lines[-1] = "input_context: []"
    else:
        lines.extend(f"  - resource: {_scalar(ref)}" for ref in input_entries)
    lines.append("")

    lines.append("output:")
    if not output_entries and not tool_check_entries:
        lines[-1] = "output: []"
    else:
        for ref, operation, match in output_entries:
            lines.append(f"  - resource: {_scalar(ref)}")
            lines.append(f"    operation: {operation}")
            match_repr = _match_flow(match)
            if match_repr is not None:
                lines.append(f"    match: {match_repr}")
        for entry in tool_check_entries:
            lines.append(f"  - tool: {_scalar(entry.tool)}")
            match_repr = _match_flow(entry.match)
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
        if hasattr(entry, "resource"):
            contract.resources.resolve(entry.resource)
    for entry in contract.output:
        if hasattr(entry, "resource"):
            contract.resources.resolve(entry.resource)


def generate_contract(
    snapshot: TraceSnapshot,
    *,
    workflow: str,
    contract_version: str = "1.0.0",
    generator: ContractGenerator | None = None,
) -> GeneratedContract:
    """Reverse-engineers a starter ``WorkflowContract`` YAML from one observed trace.

    Delegates to ``generator`` (defaulting to ``WaveMakerContractGenerator``) --
    see ``ContractGenerator`` for the pluggable-strategy interface this dispatches
    through.
    """
    return (generator or WaveMakerContractGenerator()).generate(
        snapshot, workflow=workflow, contract_version=contract_version
    )
