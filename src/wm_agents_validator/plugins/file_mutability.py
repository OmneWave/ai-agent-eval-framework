from __future__ import annotations

from wm_agents_validator.contracts.expressions import evaluate_skip_if, glob_match, resolve_path_template
from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


class FileMutabilityPlugin:
    name = "file_mutability"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        ctx = context or EvalContext()
        violations: list[Violation] = []
        changed_paths = {fc.path for fc in snapshot.file_changes}
        allowed_patterns: list[str] = []

        for resource_name, resource in contract.resources.items():
            if evaluate_skip_if(resource.skip_if, ctx):
                continue
            for file_spec in resource.files:
                resolved = resolve_path_template(file_spec.path, ctx)
                allowed_patterns.append(resolved)

                if file_spec.mutability == "read_only":
                    for path in changed_paths:
                        if glob_match(resolved, path) or path == resolved:
                            violations.append(
                                Violation(
                                    code="read_only_file_modified",
                                    message=f"Read-only file '{path}' was modified (resource '{resource_name}')",
                                    plugin=self.name,
                                    resource=resource_name,
                                    evidence={"path": path, "mutability": file_spec.mutability},
                                )
                            )

        unrelated = []
        for path in changed_paths:
            if not any(glob_match(p, path) or path == p for p in allowed_patterns):
                unrelated.append(path)

        if unrelated:
            violations.append(
                Violation(
                    code="unrelated_file_changed",
                    message=f"Files changed outside contract scope: {unrelated}",
                    plugin=self.name,
                    evidence={"unrelated_paths": unrelated, "allowed_patterns": allowed_patterns},
                )
            )

        blocking = {}
        if "no_unrelated_diff" in contract.blocking_checks:
            blocking["no_unrelated_diff"] = len(unrelated) == 0

        total_rules = sum(
            len(r.files)
            for name, r in contract.resources.items()
            if not evaluate_skip_if(r.skip_if, ctx)
        )
        score = 1.0 if not violations else max(0.0, 1.0 - len(violations) / max(total_rules, 1))

        return PluginResult(
            plugin=self.name,
            passed=len(violations) == 0,
            score=score,
            violations=violations,
            evidence={"changed_paths": sorted(changed_paths), "allowed_patterns": allowed_patterns},
            blocking_checks=blocking,
        )
