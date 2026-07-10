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

## Contract schema

Full field-by-field reference, possible values, and rationale: [docs/CONTRACT_SPEC.md](docs/CONTRACT_SPEC.md). Summary below.

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
  - resource: string
    operation: CREATE | UPDATE | DELETE

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
| `api` | `services/{name}/designtime/{name}_API.json` |
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
| `output` | Each declared `output[]` entry must be created/updated/deleted as specified, and no unrelated file changes are allowed outside the declared output scope. |
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
- A **plugin pass-rate heatmap**, toggleable between "group by Model" and "group by Contract" — pass rate (primary) + average score (secondary, diagnostic-only) per plugin per group, so you can immediately see e.g. "which model is weakest on `input_context`" or "which contract has the most `tool_calls` violations".
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

Other flags:

- `--model <name>` — only include rows whose captured `model_name` matches (client-side filter, applied after evaluation, since model is only known once a trace is normalized).
- `--user-id-key <key>` — which `TraceSnapshot.metadata` key holds the user id to show/group by in the report (default: `user_id`). Langfuse's native `userId` field is captured under this key automatically as a fallback; pass a different key if your traces stash the identifier elsewhere in trace metadata.
- `--limit <n>` — max traces to pull in time-range mode (default: 50).

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
