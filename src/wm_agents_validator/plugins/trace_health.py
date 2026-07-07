from __future__ import annotations

from wm_agents_validator.contracts.expressions import evaluate_skip_if
from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation
from wm_agents_validator.models.trace_snapshot import TraceSnapshot, _span_base_name
from wm_agents_validator.models.workflow_contract import WorkflowContract


class TraceHealthPlugin:
    name = "trace_health"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        ctx = context or EvalContext()
        violations: list[Violation] = []
        checks: dict[str, dict] = {}

        status_label = "trace status"
        if snapshot.status == "error":
            checks[status_label] = {"passed": False, "detail": "trace status is error"}
            violations.append(
                Violation(
                    code="trace_error_status",
                    message="Trace status is error",
                    plugin=self.name,
                    resource=status_label,
                )
            )
        else:
            checks[status_label] = {"passed": True, "detail": f"status={snapshot.status}"}

        error_spans_label = "error spans"
        for err in snapshot.errors:
            violations.append(
                Violation(
                    code="trace_error_span",
                    message=f"Error span: {err.name} — {err.message or 'no message'}",
                    plugin=self.name,
                    resource=error_spans_label,
                    evidence={"error": err.model_dump()},
                )
            )
        checks[error_spans_label] = (
            {"passed": False, "detail": f"{len(snapshot.errors)} error span(s) present"}
            if snapshot.errors
            else {"passed": True, "detail": "no error spans"}
        )

        javaservice_active = (
            "javaservice" in contract.resources
            and not evaluate_skip_if(contract.resources["javaservice"].skip_if, ctx)
        )
        build_passed = True
        if javaservice_active:
            build_label = "build"
            compile_spans = [
                span
                for span in snapshot.spans
                if span.type == "TOOL" and _span_base_name(span.name) == "platform_compile"
            ]
            build_passed = bool(compile_spans) and all(span.success for span in compile_spans)
            if not build_passed:
                checks[build_label] = {"passed": False, "detail": "platform_compile did not succeed"}
                violations.append(
                    Violation(
                        code="build_failed",
                        message="javaservice active but platform_compile did not succeed",
                        plugin=self.name,
                        resource=build_label,
                    )
                )
            else:
                checks[build_label] = {"passed": True, "detail": "platform_compile succeeded"}

        blocking: dict[str, bool] = {}
        if "trace_complete" in contract.blocking_checks:
            blocking["trace_complete"] = snapshot.status != "error" and not snapshot.errors
        if "diagnostics_clean" in contract.blocking_checks:
            blocking["diagnostics_clean"] = not any(
                err.message and "validation" in err.message.lower() for err in snapshot.errors
            )
        if "build_passed" in contract.blocking_checks:
            blocking["build_passed"] = build_passed if javaservice_active else True

        penalty = min(1.0, len(violations) * 0.2)
        score = max(0.0, 1.0 - penalty)

        return PluginResult(
            plugin=self.name,
            passed=len(violations) == 0,
            score=score,
            violations=violations,
            evidence={
                "status": snapshot.status,
                "error_count": len(snapshot.errors),
                "failed_tools": len(snapshot.tools_summary.failed),
                "checks": checks,
            },
            blocking_checks=blocking,
        )
