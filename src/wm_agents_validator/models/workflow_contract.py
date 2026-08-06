from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
