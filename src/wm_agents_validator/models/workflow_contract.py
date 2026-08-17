from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MatchClause(BaseModel):
    """One condition within a ``match`` list (see ``HasMatchClauses``).

    Abstract base -- each concrete clause kind is its own subclass owning its
    own ``satisfied()`` logic (a small Strategy hierarchy): evaluating a
    clause is a single polymorphic call, and adding a new clause kind means
    adding a subclass plus one branch in ``parse()``, not editing every
    existing clause's logic.
    """

    model_config = ConfigDict(extra="forbid")

    def satisfied(self, tool_input: dict[str, Any]) -> bool:
        raise NotImplementedError

    @staticmethod
    def parse(raw: object) -> "MatchClause":
        if isinstance(raw, MatchClause):
            return raw
        if isinstance(raw, str):
            return SubstringMatchClause(values=[raw])
        if isinstance(raw, list):
            return SubstringMatchClause(values=raw)
        if isinstance(raw, dict) and "regex" in raw and raw.keys() <= {"regex", "field"}:
            return RegexMatchClause.model_validate(raw)
        if isinstance(raw, dict):
            return ExactMatchClause(fields=raw)
        raise TypeError(f"invalid match clause: {raw!r} (expected a dict, a list of strings, or a {{regex: ...}} mapping)")


class ExactMatchClause(MatchClause):
    """``{field: value, ...}`` -- every key must exist literally as a
    top-level field in the call's input, value equal (case-insensitive)."""

    fields: dict[str, str | int | bool]

    def satisfied(self, tool_input: dict[str, Any]) -> bool:
        return all(str(tool_input.get(k, "")).lower() == str(v).lower() for k, v in self.fields.items())


class SubstringMatchClause(MatchClause):
    """A list of strings -- every value must appear as a substring of some
    top-level field's value in the call's input (case-insensitive); a
    field's value is stringified first, so this also reaches into nested
    objects/arrays without any special addressing syntax."""

    values: list[str]

    def satisfied(self, tool_input: dict[str, Any]) -> bool:
        haystacks = [str(v).lower() for v in tool_input.values()]
        return all(any(needle.lower() in haystack for haystack in haystacks) for needle in self.values)


class RegexMatchClause(MatchClause):
    """``{regex: "<pattern>"}``, optionally with ``field: <name>`` to scope
    the search to one top-level field instead of the whole input. ``pattern``
    is matched case-insensitively via ``re.search``."""

    regex: str
    field: str | None = None

    def satisfied(self, tool_input: dict[str, Any]) -> bool:
        haystack = str(tool_input.get(self.field, "")) if self.field else " ".join(str(v) for v in tool_input.values())
        return re.search(self.regex, haystack, re.IGNORECASE) is not None


class HasMatchClauses(BaseModel):
    """Shared ``match`` field for ``WriteSpec``/``ToolCheck``: a list of
    independent ``MatchClause`` entries, ALL of which must hold (AND)
    against one tool call's structured input. Accepts the legacy shapes
    transparently: a bare dict becomes a single ``ExactMatchClause``; a bare
    list of strings becomes a single ``SubstringMatchClause``; a mixed list
    of dicts/lists/regex-mappings is parsed per-item via ``MatchClause.parse``.
    """

    model_config = ConfigDict(extra="forbid")

    match: list[MatchClause] = Field(default_factory=list)

    @field_validator("match", mode="before")
    @classmethod
    def _normalize_match(cls, value: object) -> object:
        if not value:
            return []  # None, {}, or [] -- no match clause declared at all
        if isinstance(value, dict):
            # Legacy dict-form is unconditionally exact-match semantics -- bypass
            # parse()'s regex-sniffing so a field that happens to be named
            # "regex" is still matched literally, not misread as a RegexMatchClause.
            return [ExactMatchClause(fields=value)]
        return [MatchClause.parse(item) for item in value]


class ResourceEntry(BaseModel):
    """A single named resource -- identity (``name``) + location (``path``).

    Any other field written on an entry is treated as a further nested resource type
    scoped under it (e.g. a ``page`` entry can carry its own ``variable``/``widget``/
    ``javascript`` sub-lists) -- nesting works the same way at every level, recursively,
    for any type name, not just a fixed set. See ``ResourceRegistry.resolve()``.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    path: str

    @model_validator(mode="before")
    @classmethod
    def _coerce_nested_resource_lists(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for key, value in data.items():
            if key in ("name", "path"):
                continue
            data[key] = [entry if isinstance(entry, ResourceEntry) else ResourceEntry.model_validate(entry) for entry in value]
        return data


class ResourceRegistry(BaseModel):
    """Named registry of real resources -- pure identity (name + explicit path).

    Every entry's ``name`` is copied verbatim from the platform's resource catalog, never
    invented by a contract author. There's no fixed set of resource types -- a contract
    registers whatever type name it needs (``api``, ``page``, ``variable``, or something
    new) as ``resources.<type>: [{name, path}]``, and any entry can itself nest further
    typed sub-lists the same way (see ``ResourceEntry``). There's no built-in path
    convention either, so every entry -- at any nesting depth -- needs an explicit
    ``path``. A reference used in ``input_context``/``output`` must resolve against an
    entry actually registered here -- see ``resolve()``.
    """

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _coerce_resource_lists(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        return {
            key: [entry if isinstance(entry, ResourceEntry) else ResourceEntry.model_validate(entry) for entry in value]
            for key, value in data.items()
        }

    def resolve(self, ref: str) -> tuple[str, list[str]]:
        """Resolve a dotted ``<type>.<name>[.<subtype>.<subname>...][.<qualifier>...]``
        reference to (effective_path, qualifier_terms).

        After the top-level ``<type>.<name>`` lookup succeeds, each further pair of
        segments is tried as a nested ``<subtype>.<subname>`` descent into the current
        entry (see ``ResourceEntry``) -- as deep as the registry actually nests. The
        first pair that doesn't name a real nested type stops the descent; everything
        from there on becomes qualifier terms, checked like a ``terms`` entry -- see the
        "References and qualifiers" section of the contract schema.
        """
        parts = ref.split(".")
        if len(parts) < 2 or not parts[0]:
            raise KeyError(f"malformed resource reference '{ref}'")
        type_, name = parts[0], parts[1]
        bucket = getattr(self, type_, None)
        if bucket is None:
            raise KeyError(f"resource '{ref}' not found: no '{type_}' resources registered")
        entry = next((e for e in bucket if e.name == name), None)
        if entry is None:
            raise KeyError(f"resource '{ref}' not found in {type_}")

        remaining = parts[2:]
        while len(remaining) >= 2:
            subtype, subname = remaining[0], remaining[1]
            sub_bucket = getattr(entry, subtype, None)
            if not isinstance(sub_bucket, list) or not all(isinstance(e, ResourceEntry) for e in sub_bucket):
                break
            sub_entry = next((e for e in sub_bucket if e.name == subname), None)
            if sub_entry is None:
                raise KeyError(f"resource '{ref}' not found in {type_}.{name}.{subtype}")
            entry = sub_entry
            remaining = remaining[2:]

        return entry.path, remaining


class SkillRequirement(BaseModel):
    """One entry in ``skills.required`` -- a skill name, optionally declaring
    other required skills that must load and succeed strictly before this one
    (forming a DAG over ``required`` skills -- see ``SkillsSpec._validate_dag``
    for the cycle/reference validation, and ``plugins/skills_loaded.py`` for
    how the order itself is checked against a trace). A bare string in YAML
    (no dependencies) normalizes to ``depends_on: []`` -- see
    ``SkillsSpec._normalize_required``.

    Dependencies are scoped to other ``required`` skills only -- a name in
    ``depends_on`` must itself be a ``required`` skill's name, never an
    ``optional`` one; ``optional`` stays a plain list of strings, untouched by
    this feature, preserving its existing "documented, never required, never
    penalized either way" guarantee with no exceptions.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    depends_on: list[str] = Field(default_factory=list)


class SkillsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[SkillRequirement]
    optional: list[str] = Field(default_factory=list)

    @field_validator("required", mode="before")
    @classmethod
    def _normalize_required(cls, value: object) -> object:
        """Accepts the two legacy shapes (a bare name, or a flat list of
        names) alongside the new ``{name, depends_on}`` shape -- and any mix
        of bare names and dicts in one list -- normalizing all of them into
        a canonical list of dicts for ``SkillRequirement`` to validate.
        """
        if isinstance(value, str):
            return [{"name": value}]
        if isinstance(value, list):
            return [{"name": item} if isinstance(item, str) else item for item in value]
        return value  # let pydantic raise its normal type error for anything else

    @model_validator(mode="after")
    def _validate_dag(self) -> "SkillsSpec":
        """Validates ``required`` forms a well-formed DAG, failing loudly at
        contract-load time rather than silently producing an unenforceable
        or nonsensical dependency graph. Checked in order -- duplicate name,
        then unknown reference, then self-dependency, then general cycle --
        so each only runs once the prior ones found nothing, keeping error
        messages maximally specific instead of a confusing generic cycle
        report when the real problem is e.g. a typo'd reference.
        """
        names = [r.name for r in self.required]
        seen: set[str] = set()
        for name in names:
            if name in seen:
                raise ValueError(f"skills.required: duplicate skill name '{name}'")
            seen.add(name)

        for requirement in self.required:
            for dep in requirement.depends_on:
                if dep not in seen:
                    raise ValueError(
                        f"skills.required: '{requirement.name}' depends_on unknown skill "
                        f"'{dep}' (not declared in skills.required)"
                    )
                if dep == requirement.name:
                    raise ValueError(f"skills.required: '{requirement.name}' cannot depend on itself")

        graph = {r.name: r.depends_on for r in self.required}
        cycle = _find_dependency_cycle(graph)
        if cycle:
            raise ValueError(f"skills.required: dependency cycle detected: {' -> '.join(cycle)}")

        return self


def _find_dependency_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Small recursive DFS with a ``path`` list (for cycle reconstruction)
    and a ``done`` memo set -- clarity over Tarjan/Kahn's-algorithm
    efficiency, since a contract's skill-dependency graph is always tiny.
    Returns the cycle as a list of names (e.g. ``["a", "b", "c", "a"]``) or
    ``None`` if the graph is acyclic.
    """
    done: set[str] = set()
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in path:
            return path[path.index(node):] + [node]
        if node in done:
            return None
        path.append(node)
        for dep in graph.get(node, []):
            cycle = visit(dep)
            if cycle:
                return cycle
        path.pop()
        done.add(node)
        return None

    for start in graph:
        if start not in done:
            cycle = visit(start)
            if cycle:
                return cycle
    return None


class ToolCheck(HasMatchClauses):
    """A standalone, independent assertion: "this exact tool call happened,
    somewhere in the trace, carrying this exact content" -- with no
    connection to any ``resource:``/path at all. Lives as its own entry
    alongside ``ReadSpec``/``WriteSpec`` entries in ``input_context``/
    ``output`` (see ``WorkflowContract``), for a tool that addresses whatever
    it acts on by an identifier or other structured argument rather than a
    literal file path the framework could extract and compare against
    ``resources``' registered path.

    ``tool`` is a plain name, or a dot-separated chain describing a wrapper
    call and what it invoked (e.g. ``execute_tool.ui_applyChangesOnPageMarkup``)
    -- resolved generically by ``resolve_dotted_tool_calls``
    (``models/trace_snapshot.py``), which has no built-in knowledge of any
    specific tool's name; the chain is entirely up to the contract author.

    ``match`` (see ``HasMatchClauses``) is empty by default, meaning any call
    to ``tool`` counts.
    """

    tool: str


class ReadSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str
    terms: list[str] = Field(default_factory=list)


class WriteSpec(HasMatchClauses):
    """``match`` (see ``HasMatchClauses``) is an evidence assertion against
    the *same* evidencing tool call's structured input -- unlike ``terms``
    (substring match, anywhere in the whole trace), ``match`` clauses are
    scoped to the one call that also matched the resolved ``resource`` path.
    Empty by default -- every contract with no ``match`` clause is unaffected.
    See docs/CONTRACT_SPEC.md.
    """

    resource: str
    operation: Literal["CREATE", "UPDATE", "DELETE"]


class ToolsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class WorkflowContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: str
    contract_version: str
    name: str | None = None
    """Human-friendly display label (e.g. a page name like ``Accounts_Cards``),
    distinct from ``contract_id`` (``{workflow}@{contract_version}``, a machine
    identifier). Optional -- reports fall back to `contract_id` wherever a
    contract needs a label and `name` wasn't set, so existing contracts with
    no `name:` keep working unchanged."""
    skills: SkillsSpec
    knowledge: list[str] = Field(default_factory=list)
    resources: ResourceRegistry = Field(default_factory=ResourceRegistry)
    input_context: list[ReadSpec | ToolCheck] = Field(default_factory=list)
    """Each entry is either a ``ReadSpec`` (path-based: "this resource must be
    read") or a standalone ``ToolCheck`` (tool-based: "this exact tool call
    must have happened, with this content") -- independent of one another."""
    output: list[WriteSpec | ToolCheck] = Field(default_factory=list)
    """Each entry is either a ``WriteSpec`` (path-based: "this resource must be
    created/updated/deleted") or a standalone ``ToolCheck`` (tool-based: "this
    exact tool call must have happened, with this content") -- independent of
    one another; a ``ToolCheck`` here proves nothing about any resource's path,
    it is its own pass/fail check."""
    tools: ToolsSpec = Field(default_factory=ToolsSpec)

    @property
    def contract_id(self) -> str:
        return f"{self.workflow}@{self.contract_version}"
