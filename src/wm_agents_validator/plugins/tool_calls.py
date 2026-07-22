from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation, score_from_checks
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract
from wm_agents_validator.plugins.timing import fmt_ms, sum_duration_ms


class ToolCallsPlugin:
    """Checks the contract-wide ``tools`` policy: every ``required`` tool was
    used somewhere in the trace, and no ``forbidden`` tool was used anywhere.

    ``tools`` is one flat, global policy (not addressed to any resource) --
    neither real contract in this repo ever needed a different tool policy
    per resource, so there's no per-resource scoping here.

    ``snapshot.tool_names`` already accounts for tools invoked indirectly via
    ``execute_tool`` (wm-agent-server's generic dispatcher) -- the wrapped
    tool's own name is surfaced alongside ``"execute_tool"`` itself during
    normalization (see ``_build_tools_summary`` in ``trace/normalizer.py``),
    so a required/forbidden MCP tool reached only through ``execute_tool``
    is still checked by its real name here, not missed.
    """

    name = "tool_calls"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        violations: list[Violation] = []
        checks: dict[str, dict] = {}
        policy = contract.tools

        for required_tool in policy.required:
            used = required_tool in snapshot.tool_names
            checks[required_tool] = {
                "passed": used,
                "detail": "used" if used else "required tool never used",
            }
            if not used:
                violations.append(
                    Violation(
                        code="required_tool_missing",
                        message=f"Required tool '{required_tool}' never used",
                        plugin=self.name,
                        evidence={"required": policy.required, "actual_tools": snapshot.tool_names},
                    )
                )

        forbidden_used = [tool for tool in policy.forbidden if tool in snapshot.tool_names]
        forbidden_label = "forbidden tools"
        if forbidden_used:
            checks[forbidden_label] = {"passed": False, "detail": f"forbidden tool(s) used: {forbidden_used}"}
            violations.append(
                Violation(
                    code="forbidden_tool_used",
                    message=f"Forbidden tool(s) used: {forbidden_used}",
                    plugin=self.name,
                    evidence={"forbidden": policy.forbidden, "actual_tools": snapshot.tool_names},
                )
            )
        else:
            checks[forbidden_label] = {"passed": True, "detail": "no forbidden tool used"}

        passed, score = score_from_checks(checks)

        # Informational only -- added after scoring so it never affects
        # passed/score; see plugins/timing.py.
        tool_spans = [span for span in snapshot.spans if span.type == "TOOL"]
        tool_calls_ms = sum_duration_ms(tool_spans)
        checks["tool call time"] = {
            "passed": True,
            "detail": f"{fmt_ms(tool_calls_ms)} across {len(tool_spans)} call(s)",
        }

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=score,
            violations=violations,
            evidence={"checks": checks},
        )
