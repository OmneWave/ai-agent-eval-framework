from wm_agents_validator.models.trace_snapshot import GenerationRecord, TraceSnapshot
from wm_agents_validator.plugins.resource_usage import ResourceUsagePlugin


def test_resource_usage_reports_metrics(snapshot, contract):
    result = ResourceUsagePlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    metrics = result.evidence["metrics"]
    assert metrics["duration_ms"] == 45000
    assert metrics["total_tokens"] == 4000
    assert metrics["total_cost_usd"] == 0.03
    assert metrics["generation_count"] == 2


def test_resource_usage_always_passes_regardless_of_trace_content(snapshot, contract):
    # No contract-declared budget/limit exists anymore -- this plugin is
    # purely observational and never fails or scores, no matter the trace.
    snapshot.duration_ms = 10_000_000
    result = ResourceUsagePlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    assert result.evidence["metrics"]["duration_ms"] == 10_000_000


def test_resource_usage_handles_missing_generation_data(snapshot, contract):
    snapshot.generations = []
    result = ResourceUsagePlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.evidence["metrics"]["total_tokens"] is None
    assert result.evidence["metrics"]["total_cost_usd"] is None


def test_generation_record_totals_ignore_missing_values():
    snap = TraceSnapshot(
        trace_id="t1",
        generations=[
            GenerationRecord(total_tokens=100, cost_usd=0.01),
            GenerationRecord(total_tokens=None, cost_usd=None),
        ],
    )
    assert snap.total_tokens == 100
    assert snap.total_cost_usd == 0.01


def test_generation_record_totals_none_when_no_generations():
    snap = TraceSnapshot(trace_id="t1")
    assert snap.total_tokens is None
    assert snap.total_cost_usd is None
