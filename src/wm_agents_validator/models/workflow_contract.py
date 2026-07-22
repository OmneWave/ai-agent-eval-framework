from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# NOTE on "api": the default suffix (`_API.json`) matches JavaService/SoapService/
# DataService/SecurityService-typed services (per wm-agent-server's
# skills/common/ui/explore-api.md). A RestService/OpenAPIService-imported API (e.g. a
# Swagger import) uses `_API_REST_SERVICE.json` instead, and a WebSocketService uses
# `_API_WEBSOCKET_SERVICE.json` -- both need an explicit `path:` override on that
# registry entry, same as javaservice's real .java source below.
_PATH_CONVENTIONS = {
    "api": "services/{name}/designtime/{name}_API.json",
    "javaservice": "services/{name}/designtime/{name}_API.json",
    "db": "services/{name}/designtime/{name}_published_dataModel.json",
    "design_tokens": "src/main/webapp/pages/{name}/{name}.tokens-plan.json",
    "page": "src/main/webapp/pages/{name}/{name}.html",
    "variable": "src/main/webapp/pages/{page}/{page}.variables.json",
    "widget": "src/main/webapp/pages/{page}/{page}.html",
    "javascript": "src/main/webapp/pages/{page}/{page}.js",
}

_FLAT_TYPES = ("api", "javaservice", "db", "design_tokens")
_PAGE_SUBTYPES = ("variable", "widget", "javascript")


def _default_path(type_: str, name: str, page: str | None = None) -> str:
    return _PATH_CONVENTIONS[type_].format(name=name, page=page)


class ResourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str | None = None


class PageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str | None = None
    variable: list[ResourceEntry] = Field(default_factory=list)
    widget: list[ResourceEntry] = Field(default_factory=list)
    javascript: list[ResourceEntry] = Field(default_factory=list)


class ResourceRegistry(BaseModel):
    """Named registry of real resources -- pure identity (name + optional path override).

    Every entry's ``name`` is copied verbatim from the platform's resource catalog, never
    invented by a contract author. ``path`` is derived from type + name (+ page name, for
    page-scoped types) via ``_PATH_CONVENTIONS`` when not explicitly given.
    """

    model_config = ConfigDict(extra="forbid")

    api: list[ResourceEntry] = Field(default_factory=list)
    javaservice: list[ResourceEntry] = Field(default_factory=list)
    db: list[ResourceEntry] = Field(default_factory=list)
    design_tokens: list[ResourceEntry] = Field(default_factory=list)
    page: list[PageEntry] = Field(default_factory=list)

    def resolve(self, ref: str) -> tuple[str, list[str]]:
        """Resolve a dotted reference to (effective_path, qualifier_terms).

        Any reference segments left over after the registry lookup succeeds become
        qualifier terms, checked like a ``terms`` entry -- see the "References and
        qualifiers" section of the contract schema.

        A page-scoped reference may omit the final name segment (``page.<page>.<subtype>``,
        e.g. ``page.PetTable.variable``) -- this is the policy-constrained form: it resolves
        to the same convention path as any name-qualified entry of that subtype, without
        requiring a specific ``name`` to be pre-registered. Use this (paired with a
        ``WriteSpec.match`` clause) when a task doesn't dictate what the model should call
        the resource it creates.
        """
        parts = ref.split(".")
        if not parts or not parts[0]:
            raise KeyError(f"malformed resource reference '{ref}'")
        type_ = parts[0]

        if type_ == "page":
            if len(parts) < 2:
                raise KeyError(f"malformed resource reference '{ref}'")
            page = next((p for p in self.page if p.name == parts[1]), None)
            if page is None:
                raise KeyError(f"resource '{ref}' not found: no page named '{parts[1]}'")
            if len(parts) == 2:
                return page.path or _default_path("page", page.name), []
            if len(parts) == 3:
                # Policy-constrained reference (no name segment) -- resolves to the
                # same convention path as any name-qualified entry of this subtype,
                # with no registry entry required. Only ever the convention path: a
                # per-entry `path:` override can't apply since there's no entry to
                # read it from -- if a page-scoped subtype ever needs an override
                # path, it must be referenced by name (4-part form) instead.
                if parts[2] not in _PAGE_SUBTYPES:
                    raise KeyError(f"malformed page resource reference '{ref}'")
                return _default_path(parts[2], "", page=page.name), []
            if len(parts) < 4 or parts[2] not in _PAGE_SUBTYPES:
                raise KeyError(f"malformed page resource reference '{ref}'")
            bucket = getattr(page, parts[2])
            entry = next((e for e in bucket if e.name == parts[3]), None)
            if entry is None:
                raise KeyError(f"resource '{ref}' not found in page.{page.name}.{parts[2]}")
            path = entry.path or _default_path(parts[2], entry.name, page=page.name)
            return path, parts[4:]

        if type_ in _FLAT_TYPES:
            if len(parts) < 2:
                raise KeyError(f"malformed resource reference '{ref}'")
            bucket = getattr(self, type_)
            entry = next((e for e in bucket if e.name == parts[1]), None)
            if entry is None:
                raise KeyError(f"resource '{ref}' not found in {type_}")
            path = entry.path or _default_path(type_, entry.name)
            return path, parts[2:]

        raise KeyError(f"malformed resource reference '{ref}'")


class SkillsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: str | list[str]
    optional: list[str] = Field(default_factory=list)


class ReadSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str
    terms: list[str] = Field(default_factory=list)


class WriteSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str
    operation: Literal["CREATE", "UPDATE", "DELETE"]
    match: dict[str, str | int | bool] | list[str] = Field(default_factory=dict)
    """Evidence assertion against the *same* evidencing tool call's structured input
    -- unlike ``terms`` (substring match, anywhere in the whole trace), ``match`` is
    always an EXACT match (case-insensitive), scoped to the one call that also
    matched the resolved ``resource`` path. Two shapes:

    - dict form -- exact key=value: every key must exist literally in that call's
      input, and its value must equal the given value exactly. Use when the field
      name is known (e.g. ``{operationId: petstore_findPetsByTags}``).
    - list form -- exact value, unknown field: each value must equal exactly *some*
      field's value in that call's input, whatever key it's under. Use when the
      expected value is known but not (or shouldn't be hardcoded as) the field name
      holding it (e.g. ``[petstore_findPetsByTags]``).

    Never substring/fuzzy in either form. Defaults to ``{}`` (falsy, same as an
    empty list) -- every contract with no ``match`` clause is unaffected. See
    docs/CONTRACT_SPEC.md."""


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
    input_context: list[ReadSpec] = Field(default_factory=list)
    output: list[WriteSpec] = Field(default_factory=list)
    tools: ToolsSpec = Field(default_factory=ToolsSpec)

    @property
    def contract_id(self) -> str:
        return f"{self.workflow}@{self.contract_version}"
