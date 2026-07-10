from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


class ResourceUsagePlugin:
    """Reports a trace's duration, token, and cost usage.

    Purely observational -- there's no contract-declared budget to check
    against (see the Scoring section / removed-fields rationale in the
    contract schema), so this plugin never fails and never scores. It stays
    in the default plugin set so its numbers still show up in every report.
    """

    name = "resource_usage"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        metrics = {
            "duration_ms": snapshot.duration_ms,
            "total_tokens": snapshot.total_tokens,
            "total_cost_usd": snapshot.total_cost_usd,
            "generation_count": len(snapshot.generations),
        }

        return PluginResult(
            plugin=self.name,
            passed=True,
            score=1.0,
            violations=[],
            evidence={"metrics": metrics},
        )
