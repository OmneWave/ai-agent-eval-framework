from __future__ import annotations

from typing import Protocol

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


class EvaluatorPlugin(Protocol):
    name: str

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult: ...
