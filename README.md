# Cross-Model Benchmarking with the Evaluation Engine

## Overview

This framework is a deterministic evaluation system for agent runs. It takes a trace from an LLM-driven workflow, evaluates it against a contract defined for a specific use case, and produces a score along with detailed pass/fail evidence. Instead of relying on an LLM judge or a manually curated golden dataset, it uses structured rules and plugin-based checks to judge whether a run satisfies the expected behavior.

## What the framework does

The evaluation engine works in four stages:

1. Contract definition
   - A workflow contract is defined in YAML for a specific use case.
   - The contract describes the intended behavior, required metadata, expected skills, required tools, file scope, and blocking conditions.

2. Trace ingestion
   - The system fetches a trace or loads a saved snapshot.
   - The trace is normalized into a structured representation that captures skills, tools, file changes, agents, errors, and status.

3. [Plugin-based evaluation](#plugins)
   - The evaluation run is checked by a set of contract-driven plugins that assess skills, input context, tool usage, output changes, trace health, and usage metrics.
   - Each plugin produces a pass/fail breakdown, a score, and evidence so the report clearly shows what passed and what failed.
   - See the [Plugins](#plugins) section for the detailed behavior of each plugin.

4. Aggregated reporting
   - The framework combines plugin outputs into an overall score.
   - It also produces a verification report showing which checks passed, failed, and why.

## Why this is useful

This framework helps the WaveMaker AI platform identify the most suitable model for build use cases. It provides a consistent and objective way to evaluate models against a defined benchmark and measure their performance through a score. For enterprise teams using the platform, this enables confident decision-making by validating whether a model meets the required standards and performs reliably for business-critical workflows.

## What makes it a strong benchmark

This framework is suitable for cross-model benchmarking because it provides:

- consistent evaluation criteria
- contract-driven checks for each use case
- score breakdowns by plugin
- evidence-backed results rather than subjective opinions
- repeatability across many runs

It is especially valuable when you want to answer questions like:

- Which model best satisfies the contract for a given workflow?
- Which model is more reliable on tool usage?
- Which model has better agent coverage and planning behavior?
- Which model produces fewer trace-level errors?

## Example benchmarking approach

A simple benchmark can be structured as follows:

| Use case | Contract | Sonnet4.6 | GLM-5 40B | Ornith-1.0-35B |
|---|---|---:|---:|---:|
| UI-to-API binding | contract A | 0.86 | 0.91 | 0.83 |
| Screenshot2Code workflow | contract B | 0.72 | 0.12 | 0.68 |
| JavaService Orchestration | contract C | 0.78 | 0.84 | 0.80 |

From this, you can identify which model is strongest in which scenario and where one model is more robust than another.

## Setup

```bash
cd wm_agents_validator
uv sync --extra dev
```

Langfuse credentials are optional at setup time — pass them when you run a command (see below).

## Langfuse credentials

Priority (highest wins): **CLI flags** → **shell env vars** → **`.env.local` / `.env`**

### Option 1 — Shell env vars (recommended for CI)

```bash
LANGFUSE_SECRET_KEY=sk-... \
LANGFUSE_PUBLIC_KEY=pk-... \
LANGFUSE_BASE_URL=https://your-langfuse.example.com \
uv run fetch-trace --trace-id c4739a2868e2b7aca6430aeae2f7ea0a
```

### Option 2 — CLI flags

```bash
uv run fetch-trace \
  --langfuse-secret-key sk-... \
  --langfuse-public-key pk-... \
  --langfuse-base-url https://your-langfuse.example.com \
  --trace-id c4739a2868e2b7aca6430aeae2f7ea0a
```

### Option 3 — `.env` file (local dev)

```bash
cp .env.example .env
# Fill LANGFUSE_* values
```

### Optional: `LANGFUSE_ENVIRONMENT`

Filters every trace lookup (both `--from`/`--to` and `--filter` modes in `compare-traces`) to a
specific Langfuse `environment` tag. Defaults to `default` if not set. Same priority order as the
credentials above — `--langfuse-environment` flag, then `LANGFUSE_ENVIRONMENT` env var, then the
default.

```bash
LANGFUSE_ENVIRONMENT=prod uv run compare-traces ...
# or
uv run compare-traces --langfuse-environment prod ...
```

## Usage

Minimal — trace ID + contract only:

```bash
uv run run-verify \
  --contract contracts/binding/binding_with_widget.yaml \
  --trace-id c4739a2868e2b7aca6430aeae2f7ea0a
```

With Langfuse keys inline:

```bash
LANGFUSE_SECRET_KEY=sk-... \
LANGFUSE_PUBLIC_KEY=pk-... \
LANGFUSE_BASE_URL=https://your-langfuse.example.com \
uv run run-verify \
  --contract contracts/binding/binding_with_widget.yaml \
  --trace-id c4739a2868e2b7aca6430aeae2f7ea0a \
  --out report.json
```

Fetch a trace only:

```bash
uv run fetch-trace --trace-id c4739a2868e2b7aca6430aeae2f7ea0a
```

Debug Langfuse API / fetch issues (probe each endpoint step by step):

```bash
LANGFUSE_SECRET_KEY=sk-... \
LANGFUSE_PUBLIC_KEY=pk-... \
LANGFUSE_BASE_URL=https://your-langfuse.example.com \
uv run debug-trace --trace-id c4739a2868e2b7aca6430aeae2f7ea0a --verbose --run-fetch
```

Or set `TRACE_ID` env var:

```bash
TRACE_ID=c4739a2868e2b7aca6430aeae2f7ea0a uv run run-verify \
  --contract contracts/binding/binding_with_widget.yaml
```

Alternative trace lookup (if you don't have trace ID):

```bash
uv run fetch-trace --thread-id "proj:session" --run-id run-abc123
```

Other options:

```bash
# Run specific plugins (no Langfuse fetch — use snapshot file)
uv run run-verify \
  --contract contracts/binding/binding_with_widget.yaml \
  --snapshot tests/fixtures/trace_snapshot.json \
  --plugins skills_loaded,tool_calls

# List plugins
uv run run-verify --list-plugins
```

### Bootstrapping a contract from a trace

`generate-contract` reverse-engineers a starter contract YAML from one observed trace — either
fetched live or from a previously saved `TraceSnapshot` JSON (e.g. via `fetch-trace --out`):

```bash
uv run generate-contract --trace-id c4739a2868e2b7aca6430aeae2f7ea0a \
  --workflow screenshot_to_code --out contracts/new_workflow.yaml

# or find the trace by metadata instead of knowing its id (defaults to --limit 1 --
# generates from the single most recent match; same --filter syntax as compare-traces)
uv run generate-contract --filter projectid=WMPRJ2c9180869f6825f5019f6a6b72af0094 \
  --workflow screenshot_to_code --out contracts/new_workflow.yaml

# or from a saved snapshot file
uv run generate-contract --from-file trace_snapshot.json \
  --workflow screenshot_to_code --out contracts/new_workflow.yaml
```

It infers `resources`/`output`/`input_context` from the trace's actual file writes/edits and
`read_files` calls, `skills.required` from `skill_loads`, and `tools.required` from every tool
the trace called. **This is a starting point, not a finished contract** — it only knows what one
trace happened to do, so there's no required-vs-optional judgement on `skills`/`tools`, and every
`output` entry is checked structurally (path + operation), never for business-logic correctness.
Any path it can't map to a known resource-path convention is printed as a warning instead of
guessed at — review those, and the `match` clauses it filled in, before trusting the result.

## Contract schema

Full field-by-field reference, possible values, and rationale: [docs/CONTRACT_SPEC.md](docs/CONTRACT_SPEC.md). Summary below.

For Contract definition refere: [docs/Defining_CONTRACT.md](docs/Defining_CONTRACT.md). Summary below.


A contract has three top-level sections plus a resource registry:

```yaml
workflow: string                    # required
contract_version: string            # required

skills:
  required: string | [string]         # skill(s) that must load and succeed
  optional: [string]                  # may or may not load; never required, never flagged as extra

knowledge: [string]                 # proprietary/catalog reference paths -- always fine to read,
                                     # never required, never penalized either way

resources:                          # named registry -- pure identity (name + optional path override)
  api: [{name: string, path: string}]
  javaservice: [{name: string, path: string}]
  db: [{name: string, path: string}]
  design_tokens: [{name: string, path: string}]
  page:
    - name: string
      path: string
      variable: [{name: string, path: string}]
      widget: [{name: string, path: string}]
      javascript: [{name: string, path: string}]

input_context:                      # every entry means "must be READ somewhere in the trace"
  - resource: string                  # dotted reference, e.g. "api.hrdb" or "api.hrdb.VacationController_getVacation"
    terms: [string]                     # extra ids/keywords that must appear in some tool call's input/output

output:                             # every entry means "must be CREATED/UPDATED/DELETED"
  - resource: string                  # identity-constrained (exact name) or policy-constrained
                                       # (page.<page>.<subtype>, no name) -- see CONTRACT_SPEC.md
    operation: CREATE | UPDATE | DELETE
    match: {field: value} | [value]     # optional, default {} -- exact-match evidence assertion
                                         # against the same call that created/updated the resource

tools:                               # one flat, contract-wide tool policy
  required: [string]
  optional: [string]
  forbidden: [string]
```

**Resource names are never invented.** Every `name` under `resources` is copied verbatim from the
platform's real resource catalog (a service id, a page name, a variable/widget/javascript name) —
never an alias made up by whoever writes the contract, so two people referencing the same resource
always write the identical entry.

**Paths are derived, not typed, by default.** `path` is optional on every registry entry — when
omitted, it's computed from the resource's type + name (+ page name, for page-scoped types) via a
fixed convention built from the real WaveMaker project layout:

| Type | Convention |
|---|---|
| `api` | `services/{name}/designtime/{name}_API.json` — default only; `RestService`/`OpenAPIService` needs `_API_REST_SERVICE.json`, `WebSocketService` needs `_API_WEBSOCKET_SERVICE.json` (explicit `path:` override required for both — see [docs/CONTRACT_SPEC.md](docs/CONTRACT_SPEC.md)) |
| `javaservice` | `services/{name}/designtime/{name}_API.json` |
| `db` | `services/{name}/designtime/{name}_published_dataModel.json` |
| `design_tokens` | `src/main/webapp/pages/{name}/{name}.tokens-plan.json` |
| `page` | `src/main/webapp/pages/{name}/{name}.html` |
| `page.*.variable` | `src/main/webapp/pages/{page}/{page}.variables.json` |
| `page.*.widget` | same file as the page itself (widgets are markup inside it) |
| `page.*.javascript` | `src/main/webapp/pages/{page}/{page}.js` |

An explicit `path:` overrides this — needed for anything off-convention, like `javaservice`'s real
Java source (package-path, not name-only) or a custom query/procedure/token-override file.

**References carry qualifiers.** `input_context[].resource` / `output[].resource` are dotted
strings resolved against `resources`. Any segments left over *after* the registry lookup succeeds
become qualifier terms, checked exactly like a `terms` entry (substring match in a tool call's
input or output, anywhere in the trace) — this is what lets `api.hrdb.VacationController_getVacation`
assert both "the hrdb API file was read" *and* "that specific operation showed up somewhere",
without a separate `operationId`/`class`+`method`/`table_name`+`column_name` field per type.

## Plugins

| Plugin | Checks |
|--------|--------|
| `skills_loaded` | Required skill(s) loaded and succeeded, and no extra skills were loaded beyond the declared `required`/`optional` sets. |
| `input_context` | Each declared `input_context[]` entry must have its resolved resource actually read, and its `terms` plus any qualifier terms parsed from the reference must appear in some tool-call input or output. The plugin also reports unrelated reads outside the declared resource/knowledge scope. |
| `tool_calls` | The contract-wide `tools` policy is enforced: every `required` tool must appear in the trace and no `forbidden` tool may appear. |
| `output` | Each declared `output[]` entry must be created/updated/deleted as specified, and no unrelated file changes are allowed outside the declared output scope. A `match` clause, if present, additionally requires the resource's properties (e.g. which operation it's bound to) to be verified on the same call that created/updated it -- for resources whose exact name isn't dictated by the task. |
| `trace_health` | The trace must not be in an error state, must not contain error spans, and must pass build validation when a Java service resource is part of the output. |
| `resource_usage` | Duration, token, and cost metrics are reported for observability only; this plugin does not score or fail the run because no contract budget gate is enforced. |

Every plugin reports a full pass/fail breakdown of the named things it evaluated (one entry per resource, skill, tool, etc.), not just a single aggregate score — so both the console and HTML reports show *what* passed and *what* failed, even on a clean run. This is driven by a standard `evidence["checks"]` shape (see `PluginResult` docstring) that any plugin populates; the console/HTML renderers read it generically.

### Scoring

Modeled on SWE-bench-style binary resolution, not partial credit: **every declared check in a
plugin must pass for that plugin's `passed=True`** — no hard/soft split, no violation that "just
dilutes the score." `score` is still computed (the pass ratio over that plugin's checks) but is
diagnostic detail only, never what decides `passed` and never what should be used to rank/compare
models. A run's overall `passed` is `all(plugin.passed for plugin in results)` — one failing
plugin fails the run, same as any required test failing fails a SWE-bench instance.

The actual benchmark number for comparing models is the **pass rate** across many runs — the
fraction of (contract, model) verification runs that fully passed — which is what
`compare-traces`'s heatmap leads with (see below). Nuance for cross-model comparison comes from
aggregating binary outcomes over many runs, not from softening any single run's outcome.

## Comparing multiple traces (HTML report)

`compare-traces` verifies a batch of traces — optionally across several contracts and several LLMs at once — and renders a single self-contained HTML report:

- Sortable table with Contract, Model, User, Agent, Duration, Tokens, Cost, Score, Status, and a per-plugin status "dot strip" for an at-a-glance view of every plugin's pass/fail.
- A **per-plugin score heatmap**, toggleable between "group by Model" and "group by Contract" — average score per plugin per group (pass rate shown in the hover tooltip), so you can immediately see e.g. "which model is weakest on `input_context`" or "which contract has the most `tool_calls` violations".
- Contract / Model / Status filters + free-text search, all live-updating the table, summary cards, and heatmap together.
- Per-trace drill-down (click a row) with full plugin scores, violations, and per-generation token/cost breakdown.

No server or build step required — it's one HTML file, open it in a browser.

### Picking which traces go into the report

**1. One contract, several LLMs** (e.g. the same prompt run against different models):

```bash
uv run compare-traces \
  --contract contracts/binding/binding_with_widget.yaml \
  --trace-ids <trace-id-gpt4>,<trace-id-claude>,<trace-id-gemini> \
  --out comparison.html
```

**2. Several contracts, each with its own trace(s)** — embed each contract's trace ids directly in its own `--contract path.yaml:id1,id2` value, so the (contract, trace ids) association is explicit and self-contained instead of depending on a separate `--trace-ids` list lining up by position:

```bash
uv run compare-traces \
  --contract contracts/binding/binding_with_widget.yaml:gpt4-trace,claude-trace \
  --contract contracts/another_workflow.yaml:gpt4-trace-2,claude-trace-2 \
  --out comparison.html
```

**3. A time range** (single contract only — e.g. everything for a given user over the last day):

```bash
uv run compare-traces \
  --contract contracts/binding/binding_with_widget.yaml \
  --from 2026-07-01T00:00:00Z --to 2026-07-02T00:00:00Z \
  --user-id alice \
  --out comparison.html
```

**4. A metadata filter** (single contract only, no time range needed) — matches traces whose
`metadata` has an exact key=value match, server-side via Langfuse's own filter query (not a
client-side scan). Repeat `--filter` to AND multiple conditions:

```bash
uv run compare-traces \
  --contract contracts/binding/binding_with_widget.yaml \
  --filter workflow_name=create_variable_binding --filter model_name=glm-5 \
  --limit 20 \
  --out comparison.html
```

Note: Langfuse's trace-list API has no server-side way to filter by a trace's raw `input`/`output`
content (confirmed directly against a live instance — `column: "input"` is rejected with
`"Column input does not match a UI / CH table mapping."`) — only structured columns like
`metadata`, `name`, `environment`, `tags`, `userId`, `sessionId` are filterable. `--filter` targets
`metadata`, so it only works if your traces actually carry the relevant value there.

**Filtering by the trace's actual prompt** — since `input` isn't server-side filterable, use
`--user-prompt-contains` instead, applied client-side after fetching (same mechanism as
`--model`), against `TraceSnapshot.user_prompt` (the normalized trace input):

```bash
uv run compare-traces \
  --contract contracts/binding/binding_with_widget.yaml \
  --from 2026-07-01T00:00:00Z --to 2026-07-02T00:00:00Z \
  --user-prompt-contains "findByTags" \
  --out comparison.html
```

**5. Content search, no time range and no other selection mode at all** — give only
`--user-prompt-contains`/`--skill-name-contains` (no `--trace-ids`, `--from`/`--to`, or `--filter`):
this switches to a search mode that keeps pulling the most recent traces (20 at a time internally)
and checking each one's actual content, until `--limit` traces **actually match** — not "fetch N
candidates and see how many match," but "keep searching until N matches are found" (bounded by an
internal safety cap on total candidates scanned, in case the search term never matches):

```bash
uv run compare-traces \
  --contract contracts/binding/binding_with_widget.yaml \
  --user-prompt-contains "findByTags" --skill-name-contains "api_binding" \
  --limit 20 \
  --out comparison.html
```

This is heavier than the other modes since it fetches+normalizes every candidate it scans (not
just ones that end up matching) to inspect their content — there's no way to avoid that given
Langfuse has no server-side filter for `input`/skill names (see above). It's still cheaper than
combining `--from`/`--to` with `--user-prompt-contains`, since that combo runs full contract
verification on every candidate in the batch, not just a lightweight fetch+normalize.

Other flags:

- `--model <name>` — only include rows whose captured `model_name` matches (client-side filter, applied after evaluation, since model is only known once a trace is normalized).
- `--user-prompt-contains <text>` — only include rows whose `user_prompt` contains this text (case-insensitive substring, client-side, applied after evaluation — combinable with any trace-selection mode above, including `--filter`; used alone with no other selection mode, triggers content search mode above instead).
- `--skill-name-contains <text>` — only include rows where any loaded skill name contains this text (case-insensitive substring, client-side — `skill_names` is derived during normalization from `load_skill` tool-call spans, not a native Langfuse column, so same story as `user_prompt`).
- `--limit <n>` — max candidate traces to pull in time-range/`--filter` mode, or max **matching** traces to find in content-search mode (default: 50).
- `--user-id-key <key>` — which `TraceSnapshot.metadata` key holds the user id to show/group by in the report (default: `user_id`). Langfuse's native `userId` field is captured under this key automatically as a fallback; pass a different key if your traces stash the identifier elsewhere in trace metadata.

A trace that fails to fetch or verify doesn't abort the whole batch — it shows up in the report as an errored row with the failure reason, and every other trace still gets compared.

### Architecture (why it's structured this way)

The feature is split into small, single-purpose, swappable pieces so new discovery strategies or output formats can be added without touching existing code:

- `comparison/sources.py` — `TraceSource` protocol + `ExplicitTraceIdSource` / `TimeRangeTraceSource` (how trace IDs are discovered).
- `comparison/aggregator.py` — pure functions turning per-trace verification outcomes into a `ComparisonReport` (`build_comparison_report`) and combining several reports from different contracts into one (`merge_reports`) — no I/O.
- `comparison/pipeline.py` — `ComparisonPipeline` orchestrates source → evaluate → aggregate → filter for *one* contract, depending only on the `TraceSource` protocol and an injectable evaluator (so it's fully unit-testable without hitting Langfuse). The CLI runs one pipeline per `--contract` and merges the results.
- `report/html_comparison_renderer.py` — `ComparisonReportRenderer` protocol + `HtmlComparisonRenderer`, the only place that knows about HTML/CSS/JS (including the heatmap).
- `models/comparison.py` — `ComparisonReport` / `ComparisonRow`, the shared data contract every renderer consumes.

## Tests

```bash
uv run pytest
```
