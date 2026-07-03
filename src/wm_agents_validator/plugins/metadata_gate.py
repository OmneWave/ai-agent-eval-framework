from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


class MetadataGatePlugin:
    name = "metadata_gate"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        required = contract.required_metadata
        if not required:
            return PluginResult(plugin=self.name, passed=True, score=1.0)

        missing = [key for key in required if key not in snapshot.metadata]
        violations = [
            Violation(
                code="missing_metadata",
                message=f"Required metadata key '{key}' not found in trace",
                plugin=self.name,
                evidence={"key": key, "available_keys": list(snapshot.metadata.keys())},
            )
            for key in missing
        ]
        score = (len(required) - len(missing)) / len(required)
        return PluginResult(
            plugin=self.name,
            passed=len(missing) == 0,
            score=score,
            violations=violations,
            evidence={"missing": missing, "present": [k for k in required if k not in missing]},
        )
