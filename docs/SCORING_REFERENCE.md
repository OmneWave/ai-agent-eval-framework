# Scoring Reference — ai-agent-eval-framework

For anyone building a UI on top of this framework's evaluation reports. Model: SWE-bench-style
binary resolution — a run is **resolved or unresolved**, with no partial credit for "almost."
`overall_score` exists as a secondary, diagnostic number — never what decides pass/fail, and
never the number to rank/compare models on.

---

## 1. Per-plugin score

Every plugin evaluates a named set of checks (e.g. "required skill X loaded," "no forbidden tool
used"). From that set:

```
passed = every check in the set is true          (strict AND — no partial credit)
score  = (checks passed) / (total checks)          (a diagnostic ratio only)
```

**UI copy idea:** *"90% doesn't mean 90% correct — it means 9 of 10 checks passed, and any single
failing check still marks this plugin as failed."*

---

## 2. Per-run pass/fail and overall score

One run = one trace evaluated against one contract, across all its plugins.

```
passed        = every plugin's `passed` is true    (any one plugin failing fails the whole run)
overall_score = weighted average of each plugin's `score`
```

**Current weights** (sum to 1.0):

| Plugin | Weight | What it checks | Why this weight |
|---|---|---|---|
| `output` | **0.40** | Declared resources actually created/updated/deleted correctly; declared tool calls happened; nothing changed outside the declared scope | The actual deliverable — closest thing to "did the task succeed" |
| `skills_loaded` | **0.25** | Every required skill loaded (and in the right dependency order, if declared); no extra undeclared skills loaded | Strong proxy for the agent taking the correct approach |
| `tool_calls` | **0.20** | Every required tool was used; no forbidden tool used; no undeclared tool used | A more mechanical check — right tools used, but doesn't guarantee correct results |
| `input_context` | **0.15** | Declared resources were actually read for context; no unrelated/out-of-scope files read | Weakest signal of final correctness — an agent can under/over-read context and still land the right output |

Two more plugins run and populate the report but **do not affect `overall_score`** (zero weight):

| Plugin | Weight | Affects `passed`? | Notes |
|---|---|---|---|
| `trace_health` | 0 | **Yes** | Flags a trace with error status or error spans — a real failure signal, just not baked into the score |
| `resource_usage` | 0 | No | Purely observational (duration, tokens, cost) — always reports `passed=true` |

**UI copy idea:** *"Overall score is a weighted average, led by Output (40%) since that's the
actual deliverable. But a single failing plugin — even a 0%-weighted one like Trace Health —
still fails the run. Don't read a high score as 'passed.'"*

---

## 3. Across many runs — the real benchmark number

For comparing models/contracts, use the **pass rate**, not average `overall_score`:

```
pass rate = (runs with passed = true) / (total runs)     — per (contract, model)
```

This is the number the comparison report's heatmap leads with, and the one that should drive
any "which model is better" UI.

---

## 4. "Scope creep" / rollup checks — count doesn't matter, only presence

Several checks are a **single rollup**, not one-per-offending-item. Whether there's 1 extra
skill/unrelated file/undeclared tool or 10, it's the same one failing check, and the same capped
score penalty (never worse the more there are):

| Plugin | Rollup check | Fires on |
|---|---|---|
| `skills_loaded` | "extra skills" | Any skill loaded beyond `required` + `optional` |
| `tool_calls` | "unrelated tools" | Any tool called beyond `required`/`optional`/`forbidden` (only enforced if the contract declares *some* tool policy) |
| `input_context` | "unrelated reads" | Any file read beyond declared resources/`knowledge` (only enforced if `input_context`/`knowledge` isn't empty) |
| `output` | "unrelated changes" | Any file changed beyond declared `output` resources |

A tool call or file read that **failed** (errored out) is never counted toward any of these —
only genuinely successful calls count as real evidence of a read/write/tool-use having happened.

**UI copy idea:** *"Scope creep is pass/fail, not proportional — reading 1 unrelated file scores
the same as reading 10."*

---

## 5. Quick summary table for a tooltip/legend

| Term | Meaning |
|---|---|
| `passed` (plugin) | Every check for this plugin succeeded — no partial credit |
| `score` (plugin) | Diagnostic pass-ratio for this plugin; not used to decide `passed` |
| `passed` (run) | Every plugin in the run passed |
| `overall_score` (run) | Weighted average of plugin scores (Output 40%, Skills 25%, Tools 20%, Context 15%) — diagnostic only, never decides `passed` |
| pass rate (across runs) | The real benchmark metric — fraction of runs where `passed = true` |
