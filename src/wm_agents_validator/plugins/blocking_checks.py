from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


class BlockingChecksPlugin:
    """Runs last; aggregates blocking_checks from prior plugin results."""

    name = "blocking_checks"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
        prior_results: list[PluginResult] | None = None,
    ) -> PluginResult:
        merged: dict[str, bool] = {}
        for result in prior_results or []:
            merged.update(result.blocking_checks)

        resource_plugins = {"resource_coverage", "tool_policy", "context_grounding", "file_mutability"}
        resource_results = [r for r in (prior_results or []) if r.plugin in resource_plugins]
        all_resources_passed = all(r.passed for r in resource_results) if resource_results else True

        if "all_resources_passed" in contract.blocking_checks:
            merged["all_resources_passed"] = all_resources_passed

        for check in contract.blocking_checks:
            merged.setdefault(check, True)

        passed = all(merged.get(c, True) for c in contract.blocking_checks)

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            blocking_checks=merged,
            evidence={"blocking_checks": merged},
        )
