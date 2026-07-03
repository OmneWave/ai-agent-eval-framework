from __future__ import annotations

from wm_agents_validator.contracts.expressions import evaluate_skip_if
from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


class ResourceCoveragePlugin:
    name = "resource_coverage"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        ctx = context or EvalContext()
        agents_in_trace = snapshot.agents_in_trace
        active_resources: list[str] = []
        missing_agents: list[str] = []
        violations: list[Violation] = []
        agent_order: list[str] = []

        for delegation in snapshot.delegations:
            agent_order.append(delegation.child_agent)

        for resource_name, resource in contract.resources.items():
            if evaluate_skip_if(resource.skip_if, ctx):
                continue
            active_resources.append(resource_name)
            if resource.agent not in agents_in_trace:
                missing_agents.append(resource_name)
                violations.append(
                    Violation(
                        code="agent_not_present",
                        message=f"Resource '{resource_name}' requires agent '{resource.agent}' but it did not appear in trace",
                        plugin=self.name,
                        resource=resource_name,
                        evidence={"expected_agent": resource.agent, "agents_in_trace": sorted(agents_in_trace)},
                    )
                )

        planning_order_satisfied = True
        if active_resources and agent_order:
            expected_order = [
                contract.resources[r].agent
                for r in active_resources
                if contract.resources[r].agent in agent_order
            ]
            seen = [a for a in agent_order if a in expected_order]
            planning_order_satisfied = seen == sorted(seen, key=lambda a: expected_order.index(a) if a in expected_order else 999)

        score = 1.0 if not active_resources else (len(active_resources) - len(missing_agents)) / len(active_resources)
        blocking = {}
        if "planning_coverage_satisfied" in contract.blocking_checks:
            blocking["planning_coverage_satisfied"] = len(missing_agents) == 0
        if "planning_order_satisfied" in contract.blocking_checks:
            blocking["planning_order_satisfied"] = planning_order_satisfied

        return PluginResult(
            plugin=self.name,
            passed=len(missing_agents) == 0,
            score=score,
            violations=violations,
            evidence={
                "active_resources": active_resources,
                "missing_agents": missing_agents,
                "agents_in_trace": sorted(agents_in_trace),
                "planning_order_satisfied": planning_order_satisfied,
            },
            blocking_checks=blocking,
        )
