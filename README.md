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

3. Plugin-based evaluation
   - Multiple plugins inspect different aspects of the run:
     - metadata gate
     - intent verification
     - resource coverage
     - tool policy
     - file mutability
     - trace health
     - blocking checks
   - Each plugin returns a score, pass/fail result, and evidence.

4. Aggregated reporting
   - The framework combines plugin outputs into an overall score.
   - It also produces a verification report showing which checks passed, failed, and why.

## Why this is useful

This makes the framework well suited for evaluating whether an agent behaved correctly for a given task. It is especially useful when the same workflow needs to be tested repeatedly across different prompts, agents, or models.

The key advantage is that the evaluation is structured and repeatable. The same contract can be applied to multiple traces, and the framework will judge each one under the same rules.

## How it can be used as a Cross-Model Benchmarking Framework

A cross-model benchmark compares the same use case across different models by running the same evaluation contract against each model’s trace output.

### Benchmarking workflow

1. Define a contract for each use case
   - Example: UI-to-API binding, file-edit workflow, agent handoff workflow, or multi-step planning task.

2. Collect traces from each model
   - Run the same task using Model A, Model B, and Model C.
   - Capture the trace for each run.

3. Evaluate each trace with the same contract
   - Apply the same workflow contract to each trace.
   - This ensures fairness because every model is judged using identical criteria.

4. Compare scores and plugin results
   - Compare overall scores, pass/fail status, and plugin-level breakdowns.
   - This shows not just whether a model passed, but where it performed well or poorly.

5. Rank models per use case and overall
   - A model may excel in tool usage but struggle with planning coverage.
   - This makes the benchmark more informative than a single overall score.

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

## Best practice for using it as a benchmark

To make the framework effective for cross-model comparison:

- Use the same contract for all models in a given test case.
- Keep the task prompt and environment consistent.
- Capture enough trace detail to support all plugins.
- Compare both overall scores and plugin-level diagnostics.
- Track results over time to observe improvements or regressions.

## Summary

This evaluation engine is not just a validator; it is a structured benchmarking framework. By applying contract-driven evaluation to traces from different models, it enables fair, repeatable, and evidence-based comparison of model performance across real workflows.

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

### Optional: `--context`

You do **not** need `--context` for normal runs. It is only for advanced contracts that use path placeholders like `{page}` or `{serviceId}` in file rules. Without it, path matching uses wildcards from the trace's actual file changes.

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
  --plugins intent_verification,tool_policy

# List plugins
uv run run-verify --list-plugins
```

## Plugins

| Plugin | Checks |
|--------|--------|
| `intent_verification` | Expected skill loaded |
| `resource_coverage` | Resource agents appeared in trace |
| `tool_policy` | Required/allowed/forbidden tools per resource |
| `context_grounding` | Whether each resource's reference file(s)/context terms were actually retrieved by a tool call, vs. assumed/hallucinated — and, in the other direction, whether unrelated files were read via `read_files` that don't belong to any resource's declared scope (scope creep). Paths matching the contract's `allowed_context_reads` glob patterns (e.g. platform catalog/reference docs) are exempt from the scope-creep check — reading them is fine, not reading them is fine too |
| `file_mutability` | File path and mutability rules |
| `trace_health` | Errors, trace status |
| `resource_usage` | Trace duration, total LLM tokens, and total cost (USD) against the contract's declared `budget` |
| `blocking_checks` | Aggregates contract blocking_checks |

### Declaring a resource budget

Add an optional `budget` block to a contract to enforce duration/token/cost limits:

```yaml
budget:
  max_duration_ms: 60000
  max_total_tokens: 20000
  max_cost_usd: 0.50
```

Any field left out means that metric isn't checked. A metric is also skipped (not scored, not violated) if the trace has no data for it — e.g. Langfuse didn't return usage/cost. To make a specific metric a hard failure, add its blocking check name (`duration_within_budget`, `tokens_within_budget`, `cost_within_budget`) to `blocking_checks`.

## Comparing multiple traces (HTML report)

`compare-traces` verifies a batch of traces — optionally across several contracts and several LLMs at once — and renders a single self-contained HTML report:

- Sortable table with Contract, Model, User, Agent, Duration, Tokens, Cost, Score, Status, and a per-plugin status "dot strip" for an at-a-glance view of every plugin's pass/fail.
- A **plugin score heatmap**, toggleable between "group by Model" and "group by Contract" — average score + pass rate per plugin per group, so you can immediately see e.g. "which model is weakest on `context_grounding`" or "which contract has the most `tool_policy` violations".
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

**2. Several contracts, each with its own trace(s)** — repeat `--contract` and `--trace-ids` in matching order, one pair per contract:

```bash
uv run compare-traces \
  --contract contracts/binding/binding_with_widget.yaml --trace-ids gpt4-trace,claude-trace \
  --contract contracts/another_workflow.yaml --trace-ids gpt4-trace-2,claude-trace-2 \
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
