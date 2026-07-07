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
        checks: dict[str, dict] = {}
        changed_paths = {fc.path for fc in snapshot.file_changes}
        allowed_patterns: list[str] = []

        for resource_name, resource in contract.resources.items():
            if evaluate_skip_if(resource.skip_if, ctx):
                continue
            read_only_files = [f for f in resource.files if f.mutability == "read_only"]
            if not read_only_files:
                continue
            resource_violated_paths: list[str] = []
            for file_spec in read_only_files:
                resolved = resolve_path_template(file_spec.path, ctx)
                allowed_patterns.append(resolved)

                for path in changed_paths:
                    if glob_match(resolved, path) or path == resolved:
                        resource_violated_paths.append(path)
                        violations.append(
                            Violation(
                                code="read_only_file_modified",
                                message=f"Read-only file '{path}' was modified (resource '{resource_name}')",
                                plugin=self.name,
                                resource=resource_name,
                                evidence={"path": path, "mutability": file_spec.mutability},
                            )
                        )
            checks[resource_name] = (
                {"passed": False, "detail": f"read-only file(s) modified: {resource_violated_paths}"}
                if resource_violated_paths
                else {"passed": True, "detail": "read-only file(s) untouched"}
            )

        # allowed_patterns above only covers read_only files; editable/writable
        # files also count toward "in scope" for the unrelated-change check.
        for resource_name, resource in contract.resources.items():
            if evaluate_skip_if(resource.skip_if, ctx):
                continue
            for file_spec in resource.files:
                if file_spec.mutability != "read_only":
                    allowed_patterns.append(resolve_path_template(file_spec.path, ctx))

        unrelated = []
        for path in changed_paths:
            if not any(glob_match(p, path) or path == p for p in allowed_patterns):
                unrelated.append(path)

        unrelated_label = "unrelated changes"
        if unrelated:
            checks[unrelated_label] = {
                "passed": False,
                "detail": f"file(s) changed outside contract scope: {sorted(unrelated)}",
            }
            violations.append(
                Violation(
                    code="unrelated_file_changed",
                    message=f"Files changed outside contract scope: {unrelated}",
                    plugin=self.name,
                    resource=unrelated_label,
                    evidence={"unrelated_paths": unrelated, "allowed_patterns": allowed_patterns},
                )
            )
        else:
            checks[unrelated_label] = {"passed": True, "detail": "no changes outside contract scope"}

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
            evidence={
                "changed_paths": sorted(changed_paths),
                "allowed_patterns": allowed_patterns,
                "checks": checks,
            },
            blocking_checks=blocking,
        )
