from __future__ import annotations

from wm_agents_validator.contracts.expressions import glob_match
from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation, score_from_checks
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract

_OPERATION_TO_FILE_CHANGE_OPS: dict[str, set[str]] = {
    "CREATE": {"write", "edit"},
    "UPDATE": {"write", "edit"},
    "DELETE": {"delete"},
}


class OutputPlugin:
    """Checks whether each ``output[]`` entry's resolved resource was actually
    created/updated/deleted as declared, and that nothing outside the declared
    ``output`` scope changed.

    ``output`` is the exhaustive scope of what's allowed to change -- a
    resource that's only ever referenced under ``input_context`` (never
    ``output``) is automatically protected, since any change to it is caught
    by the unrelated-diff check below.

    Every check must pass for ``passed=True`` -- no partial credit (see the
    Scoring section of the contract schema).
    """

    name = "output"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        violations: list[Violation] = []
        checks: dict[str, dict] = {}
        changed_paths = {fc.path for fc in snapshot.file_changes}
        allowed_patterns: list[str] = []

        for write in contract.output:
            path, _qualifiers = contract.resources.resolve(write.resource)
            allowed_patterns.append(path)

            matching_ops = {fc.operation for fc in snapshot.file_changes if glob_match(path, fc.path) or fc.path == path}
            expected_ops = _OPERATION_TO_FILE_CHANGE_OPS[write.operation]
            operation_ok = bool(matching_ops & expected_ops)

            if operation_ok:
                checks[write.resource] = {"passed": True, "detail": f"{write.operation} observed on {path}"}
            else:
                checks[write.resource] = {
                    "passed": False,
                    "detail": f"expected {write.operation} on {path}, observed operations: {sorted(matching_ops) or 'none'}",
                }
                violations.append(
                    Violation(
                        code="output_operation_mismatch",
                        message=f"Resource '{write.resource}' expected {write.operation} on {path}, observed: {sorted(matching_ops) or 'none'}",
                        plugin=self.name,
                        resource=write.resource,
                        evidence={"path": path, "expected_operation": write.operation, "observed_operations": sorted(matching_ops)},
                    )
                )

        unrelated = [path for path in changed_paths if not any(glob_match(p, path) or path == p for p in allowed_patterns)]

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

        passed, score = score_from_checks(checks)

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=score,
            violations=violations,
            evidence={
                "changed_paths": sorted(changed_paths),
                "allowed_patterns": allowed_patterns,
                "checks": checks,
            },
        )
