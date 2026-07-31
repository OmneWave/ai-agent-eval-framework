from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract
from wm_agents_validator.plugins.timing import fmt_ms


class ResourceUsagePlugin:
    """Reports a trace's duration, token, and cost usage.

    Purely observational -- there's no contract-declared budget to check
    against (see the Scoring section / removed-fields rationale in the
    contract schema), so this plugin never fails and never scores; ``passed``
    is always ``True`` and ``score`` is always ``1.0``. It stays in the
    default plugin set so its numbers still show up in every report.

    Time-breakdown metrics (input-gathering time, output-generation time,
    tool-call time, error time) are reported by the plugin each one is
    actually *about* -- input_context, output, tool_calls, and trace_health
    respectively -- instead of here, so they sit next to that plugin's own
    checks rather than needing a separate resource_usage lookup.

    Populates the standard ``evidence["checks"]`` contract (see
    ``PluginResult`` docs) purely to surface these numbers in reports (console
    and HTML) that render per-plugin checks -- every entry is ``passed: True``
    since none of this is a pass/fail condition, only information.
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

        tokens_detail = f"{metrics['total_tokens']:,}" if metrics["total_tokens"] is not None else "n/a"
        cost_detail = f"${metrics['total_cost_usd']:.4f}" if metrics["total_cost_usd"] is not None else "n/a"

        checks = {
            "duration": {"passed": True, "detail": fmt_ms(snapshot.duration_ms)},
            "tokens": {"passed": True, "detail": tokens_detail},
            "cost": {"passed": True, "detail": cost_detail},
        }

        return PluginResult(
            plugin=self.name,
            passed=True,
            score=1.0,
            violations=[],
            evidence={"metrics": metrics, "checks": checks},
        )
