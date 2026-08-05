# Workflow Contract Specification

A workflow contract is a YAML file describing what an agent run *should* have done for one
use case: which skills it should load, what it should read for context, what it should
produce, and which tools it's allowed/required/forbidden to call. It's evaluated against a
trace by `run-verify` / `compare-traces` (see [README.md](../README.md)).

This document is the complete field reference — every field, its type, its possible values,
and why it exists. For the plugin behavior that reads each section, see
[README.md § Plugins](../README.md#plugins).

## Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `workflow` | `string` | yes | Identifier for the workflow this contract governs, e.g. `"ui_to_api_binding"`. |
| `contract_version` | `string` | yes | Version string, e.g. `"1.0.0"`. Combined with `workflow` to form `contract_id` (`workflow@contract_version`). |
| `name` | `string` | no, default `null` | Human-friendly display label (e.g. a page name like `Accounts_Cards`), distinct from `contract_id` (the machine identifier). Shown in `compare-traces`/`merge-html-reports` HTML output as its own filterable column (falls back to nothing shown if unset — reports don't require it). |
| `skills` | object | yes | See [Skills](#skills). |
| `knowledge` | `[string]` | no, default `[]` | See [Knowledge](#knowledge). |
| `resources` | object | no, default empty | The resource registry — see [Resources](#resources). |
| `input_context` | `[object]` | no, default `[]` | List of things that must be **read**. See [input_context](#input_context). |
| `output` | `[object]` | no, default `[]` | List of things that must be **created/updated/deleted**. See [output](#output). |
| `tools` | object | no, default all-empty | One flat, contract-wide tool policy. See [tools](#tools). |

Nothing else exists at the top level (`model_config = ConfigDict(extra="forbid")` on every
model rejects unknown fields). There is no `blocking_checks`, `slo`, or `budget` — see
[Fields that don't exist](#fields-that-dont-exist-and-why) for the fields considered and
dropped during design.

---

## Skills

```yaml
skills:
  required: string | [string]   # required
  optional: [string]            # optional, default []
```

| Field | Type | Required | Possible values | Description |
|---|---|---|---|---|
| `required` | `string` or `[string]` | yes | any skill name(s) | Skill(s) that must load **and** succeed. Checked by the `skills_loaded` plugin. Missing → `skill_not_loaded`; requested but failed → `skill_load_failed`. Both are hard failures. |
| `optional` | `[string]` | no | any skill name(s) | May load or not — never required, never counted as "extra." Loading anything **not** in `required` or `optional` is an `extra_skill_loaded` violation. |

Under the engine's scoring rule (see [Scoring](#scoring)), **every** required-skill check and
the "no extra skills" check must pass for `skills_loaded.passed = True` — there is no partial
credit for loading most-but-not-all required skills.

---

## Knowledge

```yaml
knowledge: [string]
```

A flat list of paths or glob patterns — proprietary or platform catalog/reference docs (e.g.
component/variable API reference pages). Reading them is always fine; not reading them is
always fine. Purely an exemption list from the `input_context` plugin's "unrelated reads"
scope-creep check. Not resource-backed — just raw path strings, no `name`/`path` structure.

---

## Resources

The registry: a set of **named** resource entries, grouped under type keys that are
completely open-ended — `api`, `javaservice`, `db`, `design_tokens`, `page`, `variable`,
`widget`, `javascript`, or any new type name a contract needs. There's no fixed list of
types, and any entry can itself nest further typed sub-lists the same way (e.g. a `page`
entry carrying its own `variable`/`widget`/`javascript` sub-lists) — nesting isn't limited to
`page`, or to one level deep; it works the same way at every level, for any type name.
Every entry's `name` must be the resource's real identity from the platform's catalog (a
service id, a page name, a variable/widget/javascript name) — **never an alias invented by
whoever writes the contract**. Two different contract authors referencing the same real
resource must always write the identical entry.

### Shape

```yaml
resources:
  api:           [{name: string, path: string}]
  javaservice:   [{name: string, path: string}]
  db:            [{name: string, path: string}]
  design_tokens: [{name: string, path: string}]
  page:
    - name: string
      path: string
      variable:   [{name: string, path: string}]   # nested -- any type name works here too
      widget:     [{name: string, path: string}]
      javascript: [{name: string, path: string}]
  # ...or any other type name, nested to any depth, a contract needs
```

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `string` | yes | The resource's real catalog identity. |
| `path` | `string` | yes | The file this resource lives at. There's no built-in path convention for any type, at any nesting depth — `path` must always be given explicitly. |
| *(any other key)* | `[{name, path, ...}]` | no | A further nested resource type scoped under this entry — same shape, recursively. |

A reference used in `input_context`/`output` (e.g. `api.hrdb`) only resolves if that type +
name is actually registered under `resources:` — referencing an unregistered type, name, or
nested subtype is a hard failure (`KeyError` at contract-load/evaluation time), not silently
ignored.

### Resource types

Every type name works the same way — there's no structural distinction between `page` and
any other type. `api`, `javaservice`, `db`, `design_tokens`, `page`, `variable`, `widget`,
`javascript` are the conventional names already in use across contracts, but a contract can
introduce any other type name it needs, nested or not.

| Type | Typical example |
|---|---|
| `api` | `services/hrdb/designtime/hrdb_API.json` |
| `javaservice` | `services/MyJavaService/src/.../MyJavaService.java` |
| `db` | `services/hrdb/designtime/hrdb_published_dataModel.json` |
| `design_tokens` | `src/main/webapp/pages/CreateProduct/CreateProduct.tokens-plan.json` |
| `page` | `src/main/webapp/pages/Main/Main.html` |
| `page.*.variable` (nested) | `src/main/webapp/pages/Main/Main.variables.json` |
| `page.*.widget` (nested) | `src/main/webapp/pages/Main/Main.html` (widgets are markup inside the page file, not separate files) |
| `page.*.javascript` (nested) | `src/main/webapp/pages/Main/Main.js` |

A fragment that produces its **own** file (like `createProductHeader.html`) is its own `page`
entry, not nested inside another page. A layout-plan or token-override file that's purely a
structural/style plan for one page goes under `design_tokens` with that page's name.

### Reference syntax and qualifiers

Everywhere a resource is used (`input_context[].resource`, `output[].resource`), it's a
dotted string resolved against the registry as `<type>.<name>`, optionally followed by any
number of `<subtype>.<subname>` pairs descending into nested resources — e.g. `api.hrdb`,
`page.Main`, `page.Main.variable.mainVariable`. Resolution walks as deep as the registry
actually nests: each pair is tried against the current entry's own nested lists, and the
first pair that doesn't name a real nested type stops the descent.

**Generic qualifier rule**: any reference segments left over *after* resolution succeeds
become **qualifier terms**, checked exactly like a `terms` entry (substring match against any
tool call's input or output, anywhere in the trace). This one rule replaces what would
otherwise need type-specific fields (`operationId`, `class`+`method`,
`table_name`+`column_name`):

| Reference | Resolved path | Qualifier terms |
|---|---|---|
| `api.hrdb` | `hrdb_API.json` | none |
| `api.hrdb.VacationController_getVacation` | `hrdb_API.json` | `[VacationController_getVacation]` |
| `javaservice.MyJavaService.MyJavaController.sampleMethod` | `MyJavaService_API.json` (or its explicit override) | `[MyJavaController, sampleMethod]` |
| `db.hrdb.Employee.salary` | `hrdb_published_dataModel.json` | `[Employee, salary]` |
| `page.Main.variable.mainVariable.VacationController_createVacation` | `Main.variables.json` | `[VacationController_createVacation]` |

Qualifiers work identically whether the reference appears under `input_context` or `output`
— an `output`-side qualifier is checked by the `input_context` plugin's term logic, since
`output` itself has no content-relevance check of its own.

If a task legitimately gives the model free choice over naming (e.g. "bind list1 to the
findByTags operation" doesn't say what the resulting variable should be called), there's no
way to reference the not-yet-named resource directly — register it under whatever name the
trace actually used once observed, or rely on a `match` clause (see [output](#output)) against
a resource referenced by its type alone at a broader granularity instead.

A dangling reference (unknown type, unknown name at any level, malformed dotted string)
raises a `ValueError` naming the contract file and the bad reference **at load time**
(`contracts/loader.py`), before any plugin runs.

---

## input_context

```yaml
input_context:
  - resource: string            # required
    terms: [string]             # optional, default []
```

Every entry means: **this resource must be read somewhere in the trace.**

| Field | Type | Required | Description |
|---|---|---|---|
| `resource` | `string` | yes | Dotted reference, resolved via `resources` (see above). |
| `terms` | `[string]` | no, default `[]` | Free-form ids/keywords that must appear in **some** *read*-tool call's input or output, anywhere in the trace. Combined with any qualifier terms parsed from `resource`. |

Checked by the `input_context` plugin:
- Was the resolved path actually retrieved (via `read_files`)?
- Were all `terms` + qualifier terms observed in a **read**-tool call's input **or** output —
  either side counts, but only among read tools (`INPUT_GATHERING_TOOLS`: `read_files`,
  `grep_in_files`, `find_files_by_glob`, `get_tool_schema`, and the `platform_get*`/`platform_list*`
  lookup tools). A word appearing only in an unrelated *write* call never grounds a term — that's
  `match`'s job (see [output](#output)), checked separately against write-tool calls.
- (Inverse direction, contract-wide) Were any files read via `read_files` that aren't
  declared anywhere under `input_context`/`output`, and aren't in `knowledge`? (scope creep) —
  **only enforced as a failure when the contract actually declared some context expectation**
  (`input_context` and/or `knowledge` non-empty). A contract with both empty has expressed no
  opinion about what should be read, so unrelated reads are reported informationally only in
  that case, never as a failure — otherwise this would be the *only* check in the plugin for
  such a contract, and a single scope-creep flag would zero out the whole plugin's score
  regardless of every other (declared, passing) resource.
- (Contract-wide) Were all qualifier terms parsed from **`output[]`** references also
  observed somewhere in the trace? (since `output` has no content-check of its own; this one
  stays trace-wide rather than read-tool-scoped, since an output qualifier like an `operationId`
  typically surfaces in the write/creation call itself, not a read call)

Under the strict scoring rule, **every** one of the above must hold for
`input_context.passed = True` — a missing term, a missing path, or one unrelated read (when
scope was actually declared) all fail the plugin, not just dilute its score.

---

## output

```yaml
output:
  - resource: string                      # required
    operation: CREATE | UPDATE | DELETE     # required
    match: {field: value, ...} | [value, ...]  # optional, default {}
```

Every entry means: **this resource must be created/updated/deleted.**

| Field | Type | Required | Possible values | Description |
|---|---|---|---|---|
| `resource` | `string` | yes | any valid dotted reference | Resolved via `resources`. |
| `operation` | `string` | yes | `CREATE`, `UPDATE`, `DELETE` | The expected file operation. Checked against the trace's actual `FileChangeRecord.operation` — `CREATE`/`UPDATE` accept an observed `write` or `edit`; `DELETE` requires an observed `delete`. Mismatch → `output_operation_mismatch`. |
| `match` | `dict` or `list` | no, default `{}` | any field:value pairs, or any list of values | Evidence assertion against the *same* tool call whose input also matched this entry's resolved path (an "evidencing call") — see below. Mismatch → `output_match_mismatch`. |

### `match` — a scoped evidence assertion (unlike `terms`, tied to one specific call)

`match` and `terms` (see [input_context](#input_context)) differ in **which calls they inspect**,
mirroring the two plugins' own responsibilities: `terms` verifies what got *read* (scoped to
read-tool calls, input and output — see above); `match` verifies what got *written* (scoped to
write-tool calls, input only — `OUTPUT_GENERATION_TOOLS`: `write_file`, `edit_file_content`,
`delete_file`, `ui_createApiAwareVariable`, `ui_createNonApiAwareVariable`, `ui_updateVariable`,
`platform_createWebPage`, `platform_compile`). Within that write-tool scope, `match` is further
narrowed to the *one call* that also matched this entry's resolved path (the "evidencing call" —
see the coherence rule below). Two shapes, with different matching semantics because they fit
different tool-argument shapes:

- **dict form** — `{field: value, ...}`: **exact match**. Every key must exist literally in the
  evidencing call's structured *input*, and its value must equal the given value exactly
  (case-insensitive). For tools with flat, short scalar arguments where the field name is known
  (e.g. `ui_createApiAwareVariable`'s `operationId`):
  ```yaml
  match:
    operationId: petstore_findPetsByTags
  ```
- **list form** — `[value, ...]`: **substring match**. Every value must appear as a substring of
  some value in that same call's input (case-insensitive). Use this shape when the expected value
  is known but the field name isn't (e.g. it may differ across tool versions), or when the value
  lives inside a larger content blob rather than being a field's entire value — e.g. a widget tag
  inside `write_file`'s `file_content` (a short keyword can never *equal* a whole file's content,
  only appear within it):
  ```yaml
  match: [petstore_findPetsByTags]
  # or, checking markup content written by write_file:
  match: [wm-button]
  ```

**Coherence rule**: everything in `match` must be satisfied on the *same* write-tool call that also
matched the resolved `resource` path — never split across two different calls, and never satisfied
by a read call even if it carries the same value. This is found by first narrowing the trace to
"evidencing spans" (`TOOL` spans whose base name is in `OUTPUT_GENERATION_TOOLS` **and** whose
extracted input paths match the resolved path), then checking `match` only against those spans'
own input. A call that only matches the path but not every `match` condition, or a *different*
call elsewhere in the trace that happens to carry one of the `match` values but never touched this
resource, never counts.

**Still permissive across *which* call**: if multiple evidencing calls exist (e.g. a retry after
an earlier mistake), only one of them needs to satisfy `match` (`any()` match, same "first match
anywhere wins" philosophy as `terms`) — a wrong-then-corrected attempt still passes. This is a
deliberate softness, not a bug: `match`'s purpose is to prove the resource was created with the
right properties *at least once* in the trace, not that the agent got it right immediately.

`match` defaults to `{}` — a contract with no `match` clause behaves exactly as before this field
existed.

Every resource resolved from `output` collectively defines the **exhaustive** set of things
allowed to change. Anything in the trace's file changes that doesn't match any `output` entry
is a violation (`unrelated_file_changed`) — this single mechanism covers both "no scope
creep" and "nothing protected got touched." There is no separate `protected:` list: a
resource that's only ever referenced under `input_context` (never `output`) is automatically
protected, because any change to it is caught by this same check.

**Resolved — platform-created resources.** `FileChangeRecord` extraction
(`TraceSnapshot.file_changes`) used to only recognize `write_file`/`edit_file_content`/
`delete_file` calls as write evidence, leaving variable creation via a platform tool (e.g.
`ui_createApiAwareVariable`/`ui_createNonApiAwareVariable`/`ui_updateVariable`) with no evidence
at all whenever it wasn't also accompanied by a direct file-editing call. A real trace (not this
repo's earlier synthetic stand-in) confirmed exactly that: a variable created purely via
`ui_createNonApiAwareVariable`, no `.variables.json` write/edit anywhere in the trace.
`file_changes` now also synthesizes a `write`/`edit` `FileChangeRecord` for `VARIABLE_CREATE_TOOLS`
calls (path derived from `pageName`, or from a `path`/`file_path` field when `pageName` isn't
present — both shapes are observed across real vs. fixture traces), and `extract_paths_from_input`
resolves the same path for these tools, so `output`'s `match`-evidence lookup (which filters
evidencing spans by extracted path) agrees with the operation check on what a variable-creation
call touched.

---

## tools

```yaml
tools:
  required: [string]    # optional, default []
  optional: [string]    # optional, default []
  forbidden: [string]   # optional, default []
```

One flat, **contract-wide** policy — not addressed to any resource. (Earlier drafts scoped
`tools` per resource; neither real contract in this repo ever needed a different policy per
resource, and `required`/`forbidden` were already checked globally in the implementation, so
the per-resource address was dropped.)

| Field | Type | Possible values | Description |
|---|---|---|---|
| `required` | `[string]` | any tool name(s) | Must be called somewhere in the trace. Missing → `required_tool_missing`. |
| `optional` | `[string]` | any tool name(s) | Documentation only — may or may not be used, never checked. Renamed from `allowed`: the old name implied a whitelist that never actually existed; the real behavior has always been "documented, never required, never penalized either way." |
| `forbidden` | `[string]` | any tool name(s) | Must not be used **anywhere** in the trace. Violated → `forbidden_tool_used`. |

---

## Scoring

Modeled on how SWE-bench and comparable agent benchmarks score: a task instance is
**binary — resolved or unresolved** (every `FAIL_TO_PASS` test must pass; there's no partial
credit for "almost" fixing the bug). The headline benchmark number is the **resolve rate** —
the fraction of instances resolved, aggregated over many instances.

Mapped onto this engine: one verification run (one trace against one contract) is the
equivalent of one SWE-bench "instance."

- **Per plugin**: every plugin evaluates a named set of checks (`evidence["checks"]`).
  `passed = all(check["passed"] for check in checks)` — every declared check must hold. There
  is no hard/soft split and no dilution-only violation that lets a score slide while still
  marking `passed=True`. `score = count(passed) / count(total)` over that same map — kept
  only as **diagnostic detail** inside the report, never used to decide `passed`, and never
  the primary number for ranking/comparing models.
- **Per run**: `passed = all(plugin.passed for plugin in results)` — one failing plugin fails
  the run, matching SWE-bench's "any required test failing = unresolved." `overall_score`
  (weighted average of plugin scores) is still computed and shown, but is explicitly
  secondary — a "how close" number, not what cross-model rankings are built on.
- **Across runs** (the actual benchmark number): the **pass rate** —
  `count(runs with passed=True) / count(runs)` per (contract, model) — is the
  SWE-bench-equivalent resolve rate, and is what `compare-traces`'s heatmap leads with.

### Per-plugin checks

| Plugin | Checks (each is one `passed: bool` entry in `evidence["checks"]`) |
|---|---|
| `skills_loaded` | one per skill in `skills.required` ("loaded successfully"); one rollup ("no skills loaded beyond `required`+`optional`") |
| `input_context` | one per `input_context[]` entry ("resource actually read" + "declared terms/qualifiers observed"); one rollup for output-side qualifiers; one rollup ("no unrelated `read_files` outside `knowledge` + referenced resources") |
| `tool_calls` | one per tool in `tools.required` ("used somewhere in the trace"); one rollup ("no `tools.forbidden` tool used anywhere") |
| `output` | one per `output[]` entry ("correct create/update/delete operation"); one rollup ("no unrelated file change") |
| `trace_health` | "trace status is not error"; "no error spans"; "build passed" (only present when a `javaservice`-typed resource is in `output`) |
| `resource_usage` | none — no checks, always `passed=True`, purely observational metrics in `evidence["metrics"]` |

---

## Fields that don't exist, and why

These were considered during design and deliberately dropped. Listed so nobody goes looking
for them:

| Removed field | Why |
|---|---|
| `mutability` (per output file) | Purely descriptive, nothing enforced it. The one thing it gestured at ("only touched via a specific tool") is fully expressible via `tools.required`/`tools.forbidden`. |
| `output.protected` | Redundant — `output` is already the exhaustive allowed-change list; anything else is caught by the unrelated-diff check. |
| `expect_contains` | Content-correctness checking (asserting exact file/tool-call content) is out of scope for this engine. `terms`/qualifiers are the only content-relevance signal, and they're soft/global (presence anywhere), not exact-match. |
| `blocking_checks` / `slo` | Every plugin already computes its own `passed` from its own checks. A separate named-gate list layered on top was redundant indirection. `slo` was informational only and unused by any plugin. |
| `skip_if` (per entry) | Every `input_context`/`output` entry is unconditionally required for every run of that contract. A task variant that doesn't need a given read/write needs its own contract, not a conditional flag on a shared one. |
| `budget` (duration/token/cost ceiling) | No contract-declared limit, no pass/fail gate on resource usage. `resource_usage` still reports the numbers; it just never fails or scores anything from them. |
| `agent` (per resource) | Was only checked by the now-removed `resource_coverage` plugin (agent-presence + planning-order). Pure documentation label otherwise, with nothing left to enforce it. |
| `allowed` (renamed to `optional`, on `skills` and `tools`) | Not removed, renamed — "allowed" implied a whitelist that was never real; the actual semantic ("documented, never required, never penalized either way") is what `optional` states directly. |

---

## Full example

```yaml
workflow: ui_to_api_binding
contract_version: "1.0.0"
name: PetTable

skills:
  required: [ui_to_api_binding_workflow, variables, actions, markup]
  optional: [explore-codebase, explore-api]

knowledge:
  - /catalog/components/wm-table/wm-table.md
  - /catalog/variables/ApiAwareVariable/ApiAwareVariable.md

resources:
  api:
    - name: petstore
      path: services/petstore/designtime/petstore_API_REST_SERVICE.json
  page:
    - name: PetTable
      path: src/main/webapp/pages/PetTable/PetTable.html
      variable:
        - name: findPetsByTagsVariable
          path: src/main/webapp/pages/PetTable/PetTable.variables.json
      widget:
        - name: swagger_findPetsByTagsTable1
          path: src/main/webapp/pages/PetTable/PetTable.html

input_context:
  - resource: api.petstore.petstore_findPetsByTags

output:
  - resource: page.PetTable.variable.findPetsByTagsVariable
    operation: CREATE
    match:
      operationId: petstore_findPetsByTags
  - resource: page.PetTable.widget.swagger_findPetsByTagsTable1
    operation: UPDATE

tools:
  required: [read_files, ui_createApiAwareVariable]
  optional: [platform_getServiceDetails, platform_getDefinitionInformation, edit_file_content, write_file]
  forbidden: [delete_file]
```

See [contracts/binding/binding_with_widget.yaml](../contracts/binding/binding_with_widget.yaml)
and [contracts/screenshot_to_code/screenshot_to_code_v1.yaml](../contracts/screenshot_to_code/screenshot_to_code_login_v1.yaml)
for the real contracts this schema is used by.
