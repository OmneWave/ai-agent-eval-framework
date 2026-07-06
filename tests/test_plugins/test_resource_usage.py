from wm_agents_validator.models.trace_snapshot import GenerationRecord
from wm_agents_validator.models.workflow_contract import BudgetSpec
from wm_agents_validator.plugins.resource_usage import ResourceUsagePlugin


def test_resource_usage_passes_within_fixture_budget(snapshot, contract):
    result = ResourceUsagePlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    assert result.evidence["metrics"]["duration_ms"]["actual"] == 45000
    assert result.evidence["metrics"]["total_tokens"]["actual"] == 4000
    assert result.evidence["metrics"]["total_cost_usd"]["actual"] == 0.03
    # Standard evidence["checks"] contract: every metric with a declared
    # budget shows up, pass or fail, so a clean pass still surfaces what was
    # actually verified instead of nothing at all.
    assert all(c["passed"] for c in result.evidence["checks"].values())
    assert set(result.evidence["checks"]) == {
        "Trace duration (ms)",
        "Total tokens",
        "Total cost (USD)",
    }


def test_resource_usage_checks_evidence_reflects_failures(snapshot, contract):
    contract.budget = BudgetSpec(max_total_tokens=100, max_cost_usd=0.001)
    result = ResourceUsagePlugin().evaluate(snapshot, contract)

    checks = result.evidence["checks"]
    assert checks["Total tokens"]["passed"] is False
    assert "exceeded budget" in checks["Total tokens"]["detail"]
    # Duration had no budget declared here, so it's skipped entirely rather
    # than reported as a misleading pass/fail.
    assert "Trace duration (ms)" not in checks

    # The violation is tagged with the matching check label so renderers can
    # de-duplicate the two views of the same failure.
    token_violation = next(v for v in result.violations if v.code == "token_budget_exceeded")
    assert token_violation.resource == "Total tokens"


def test_resource_usage_no_budget_declared_always_passes(snapshot, contract):
    contract.budget = None
    result = ResourceUsagePlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []


def test_resource_usage_flags_duration_over_budget(snapshot, contract):
    contract.budget = BudgetSpec(max_duration_ms=1000)
    result = ResourceUsagePlugin().evaluate(snapshot, contract)
    assert not result.passed
    assert result.score < 1.0
    codes = [v.code for v in result.violations]
    assert "duration_budget_exceeded" in codes


def test_resource_usage_flags_token_and_cost_over_budget(snapshot, contract):
    contract.budget = BudgetSpec(max_total_tokens=100, max_cost_usd=0.001)
    result = ResourceUsagePlugin().evaluate(snapshot, contract)
    assert not result.passed
    codes = {v.code for v in result.violations}
    assert codes == {"token_budget_exceeded", "cost_budget_exceeded"}
    # score degrades proportionally to overage rather than falling to 0
    assert 0.0 < result.score < 1.0


def test_resource_usage_ignores_metric_with_no_data(snapshot, contract):
    # Trace has no generations at all -> tokens/cost can't be verified, so
    # those budget limits shouldn't be scored or violated, only duration.
    snapshot.generations = []
    contract.budget = BudgetSpec(max_duration_ms=60000, max_total_tokens=100, max_cost_usd=0.001)

    result = ResourceUsagePlugin().evaluate(snapshot, contract)

    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    assert result.evidence["metrics"]["total_tokens"]["actual"] is None


def test_resource_usage_sets_blocking_check_when_declared(snapshot, contract):
    contract.budget = BudgetSpec(max_duration_ms=1000)
    contract.blocking_checks = [*contract.blocking_checks, "duration_within_budget"]

    result = ResourceUsagePlugin().evaluate(snapshot, contract)

    assert result.blocking_checks == {"duration_within_budget": False}


def test_resource_usage_blocking_check_not_set_when_not_declared(snapshot, contract):
    contract.budget = BudgetSpec(max_duration_ms=1000)
    result = ResourceUsagePlugin().evaluate(snapshot, contract)
    assert result.blocking_checks == {}


def test_generation_record_totals_ignore_missing_values():
    from wm_agents_validator.models.trace_snapshot import TraceSnapshot

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
    from wm_agents_validator.models.trace_snapshot import TraceSnapshot

    snap = TraceSnapshot(trace_id="t1")
    assert snap.total_tokens is None
    assert snap.total_cost_usd is None
