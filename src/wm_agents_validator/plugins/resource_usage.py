from __future__ import annotations

from typing import Any

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract

# (snapshot attribute, budget attribute, violation code, human label, blocking check name)
_METRICS: tuple[tuple[str, str, str, str, str], ...] = (
    ("duration_ms", "max_duration_ms", "duration_budget_exceeded", "Trace duration (ms)", "duration_within_budget"),
    ("total_tokens", "max_total_tokens", "token_budget_exceeded", "Total tokens", "tokens_within_budget"),
    ("total_cost_usd", "max_cost_usd", "cost_budget_exceeded", "Total cost (USD)", "cost_within_budget"),
)


class ResourceUsagePlugin:
    """Checks a trace's duration, token, and cost usage against the budget
    declared in the contract (``contract.budget``).

    Duration, tokens, and cost are evaluated together in one plugin because
    they're the same kind of check (actual vs. a declared limit) over the
    same trace, and are inherently correlated — cost is derived from tokens,
    and duration tends to track both. Each metric only degrades the score
    proportionally to how far over budget it is (not a hard cliff to zero),
    and only becomes a hard failure if its blocking check is explicitly
    listed in ``contract.blocking_checks``.

    If the contract declares no budget at all, or a given trace has no data
    for a metric (e.g. Langfuse didn't return usage/cost for this trace),
    that metric is skipped rather than penalized — we only score what we can
    actually verify.
    """

    name = "resource_usage"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        budget = contract.budget
        violations: list[Violation] = []
        blocking: dict[str, bool] = {}
        metric_scores: list[float] = []
        metrics_evidence: dict[str, Any] = {}
        checks_evidence: dict[str, Any] = {}

        for snapshot_attr, budget_attr, code, label, check_name in _METRICS:
            actual = getattr(snapshot, snapshot_attr)
            limit = getattr(budget, budget_attr) if budget else None

            metrics_evidence[snapshot_attr] = {"actual": actual, "limit": limit}

            if limit is None or actual is None:
                # Nothing to verify (no budget declared, or no data for this
                # metric) -- skip it rather than reporting a misleading pass/fail.
                continue

            within_budget = actual <= limit
            metric_scores.append(1.0 if within_budget else max(0.0, limit / actual) if actual else 1.0)

            if check_name in contract.blocking_checks:
                blocking[check_name] = within_budget

            if within_budget:
                checks_evidence[label] = {"passed": True, "detail": f"{actual} within budget of {limit}"}
            else:
                checks_evidence[label] = {
                    "passed": False,
                    "detail": f"{actual} exceeded budget of {limit}",
                }
                violations.append(
                    Violation(
                        code=code,
                        message=f"{label} of {actual} exceeded budget of {limit}",
                        plugin=self.name,
                        resource=label,
                        evidence={"actual": actual, "limit": limit},
                    )
                )

        score = sum(metric_scores) / len(metric_scores) if metric_scores else 1.0
        passed = len(violations) == 0

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=round(score, 4),
            violations=violations,
            evidence={
                "metrics": metrics_evidence,
                "generation_count": len(snapshot.generations),
                "budget": budget.model_dump() if budget else None,
                "checks": checks_evidence,
            },
            blocking_checks=blocking,
        )
