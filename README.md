# wm_agents_validator

Validate WaveMaker agent runs by fetching Langfuse traces, normalizing them into a `TraceSnapshot`, and evaluating them against `WorkflowContract` YAML specs using pluggable deterministic plugins.

No golden dataset. No LLM judge.

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
  --contract contracts/ui_to_api_binding_v1.yaml \
  --trace-id c4739a2868e2b7aca6430aeae2f7ea0a
```

With Langfuse keys inline:

```bash
LANGFUSE_SECRET_KEY=sk-... \
LANGFUSE_PUBLIC_KEY=pk-... \
LANGFUSE_BASE_URL=https://your-langfuse.example.com \
uv run run-verify \
  --contract contracts/ui_to_api_binding_v1.yaml \
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
  --contract contracts/ui_to_api_binding_v1.yaml
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
  --contract contracts/ui_to_api_binding_v1.yaml \
  --snapshot tests/fixtures/trace_snapshot.json \
  --plugins intent_verification,tool_policy

# List plugins
uv run run-verify --list-plugins
```

## Plugins

| Plugin | Checks |
|--------|--------|
| `metadata_gate` | Required metadata keys present |
| `intent_verification` | Expected skill loaded |
| `resource_coverage` | Resource agents appeared in trace |
| `tool_policy` | Required/allowed/forbidden tools per resource |
| `file_mutability` | File path and mutability rules |
| `trace_health` | Errors, trace status |
| `blocking_checks` | Aggregates contract blocking_checks |

## Tests

```bash
uv run pytest
```
