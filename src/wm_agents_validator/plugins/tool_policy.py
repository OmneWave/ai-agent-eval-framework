from __future__ import annotations

from wm_agents_validator.contracts.expressions import evaluate_skip_if, glob_match, resolve_path_template
from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


class ToolPolicyPlugin:
    name = "tool_policy"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        ctx = context or EvalContext()
        violations: list[Violation] = []
        checks: dict[str, dict] = {}
        active_count = 0
        passed_count = 0

        for resource_name, resource in contract.resources.items():
            if evaluate_skip_if(resource.skip_if, ctx):
                continue
            active_count += 1
            policy = resource.tools
            resource_passed = True
            reasons: list[str] = []
            resource_paths = [
                resolve_path_template(f.path, ctx) for f in resource.files
            ]

            for required_tool in policy.required:
                if required_tool not in snapshot.tool_names:
                    resource_passed = False
                    reasons.append(f"required tool '{required_tool}' never used")
                    violations.append(
                        Violation(
                            code="required_tool_missing",
                            message=f"Resource '{resource_name}' requires tool '{required_tool}'",
                            plugin=self.name,
                            resource=resource_name,
                            evidence={"required": policy.required, "actual_tools": snapshot.tool_names},
                        )
                    )

            for forbidden_tool in policy.forbidden:
                if not self._forbidden_tool_violates(
                    forbidden_tool, resource_paths, snapshot
                ):
                    continue
                resource_passed = False
                reasons.append(f"forbidden tool '{forbidden_tool}' used on its file scope")
                violations.append(
                    Violation(
                        code="forbidden_tool_used",
                        message=(
                            f"Resource '{resource_name}' forbids tool '{forbidden_tool}' "
                            f"on its file scope"
                        ),
                        plugin=self.name,
                        resource=resource_name,
                        evidence={
                            "forbidden": policy.forbidden,
                            "resource_paths": resource_paths,
                        },
                    )
                )

            checks[resource_name] = {
                "passed": resource_passed,
                "detail": "; ".join(reasons) if reasons else "required tools used, no forbidden tool used",
            }
            if resource_passed:
                passed_count += 1

        score = 1.0 if active_count == 0 else passed_count / active_count
        return PluginResult(
            plugin=self.name,
            passed=len(violations) == 0,
            score=score,
            violations=violations,
            evidence={"active_resources": active_count, "passed_resources": passed_count, "checks": checks},
        )

    def _forbidden_tool_violates(
        self,
        forbidden_tool: str,
        resource_paths: list[str],
        snapshot: TraceSnapshot,
    ) -> bool:
        """Forbidden if the tool appears and touches this resource's file paths."""
        matching_changes = [
            fc
            for fc in snapshot.file_changes
            if fc.tool_name == forbidden_tool
            and any(glob_match(p, fc.path) or fc.path == p for p in resource_paths)
        ]
        if matching_changes:
            return True
        return not resource_paths and forbidden_tool in snapshot.tool_names
