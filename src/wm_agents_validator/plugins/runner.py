from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.verification import VerificationReport
from wm_agents_validator.models.workflow_contract import WorkflowContract
from wm_agents_validator.plugins.blocking_checks import BlockingChecksPlugin
from wm_agents_validator.plugins.registry import DEFAULT_PLUGINS, PLUGIN_WEIGHTS, get_plugin


def run_plugins(
    snapshot: TraceSnapshot,
    contract: WorkflowContract,
    plugins: list[str] | None = None,
    context: EvalContext | None = None,
) -> VerificationReport:
    plugin_names = [name for name in (plugins or DEFAULT_PLUGINS) if name != "blocking_checks"]
    ctx = context or EvalContext()
    results: list[PluginResult] = []

    for name in plugin_names:
        plugin = get_plugin(name)
        results.append(plugin.evaluate(snapshot, contract, ctx))

    results.append(
        BlockingChecksPlugin().evaluate(snapshot, contract, ctx, prior_results=results)
    )

    blocking_checks: dict[str, bool] = {}
    all_violations: list[Violation] = []
    weighted_score = 0.0
    weight_total = 0.0

    for result in results:
        blocking_checks.update(result.blocking_checks)
        all_violations.extend(result.violations)
        weight = PLUGIN_WEIGHTS.get(result.plugin, 0.0)
        if weight > 0:
            weighted_score += result.score * weight
            weight_total += weight

    overall_score = weighted_score / weight_total if weight_total else 0.0
    if contract.blocking_checks:
        passed = all(blocking_checks.get(c, True) for c in contract.blocking_checks)
    else:
        passed = all(r.passed for r in results)

    return VerificationReport(
        trace_id=snapshot.trace_id,
        contract_id=contract.contract_id,
        passed=passed,
        overall_score=round(overall_score, 4),
        plugin_results=results,
        blocking_checks=blocking_checks,
        violations=all_violations,
    )
