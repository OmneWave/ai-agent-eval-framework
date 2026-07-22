from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation, score_from_checks
from wm_agents_validator.models.trace_snapshot import TraceSnapshot, _span_base_name
from wm_agents_validator.models.workflow_contract import WorkflowContract
from wm_agents_validator.plugins.timing import fmt_ms, sum_duration_ms


class TraceHealthPlugin:
    name = "trace_health"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        violations: list[Violation] = []
        checks: dict[str, dict] = {}

        # `snapshot.status == "error"` and `snapshot.errors` being non-empty
        # are, in the overwhelming common case, the SAME underlying fact seen
        # two ways: `_derive_status` sets status="error" precisely when a
        # tool call failed (or a span's level is ERROR) -- exactly the
        # condition `errors` itself walks the spans for. Scoring them as two
        # separate checks double-counts one root cause as two failures, which
        # -- especially for a plugin with as few checks as this one -- can
        # swing the whole plugin's score from "one recoverable hiccup" all
        # the way to a stark 0%, misleadingly implying total failure. One
        # merged check keeps the trace-status signal (still catches the rare
        # case where status is "error" for a reason with no matching span,
        # e.g. a trace-level flag alone) without counting it twice.
        health_label = "trace health"
        if snapshot.status == "error":
            violations.append(
                Violation(
                    code="trace_error_status",
                    message="Trace status is error",
                    plugin=self.name,
                    resource=health_label,
                )
            )
        for err in snapshot.errors:
            violations.append(
                Violation(
                    code="trace_error_span",
                    message=f"Error span: {err.name} — {err.message or 'no message'}",
                    plugin=self.name,
                    resource=health_label,
                    evidence={"error": err.model_dump()},
                )
            )

        if snapshot.status == "error" or snapshot.errors:
            reasons = []
            if snapshot.status == "error":
                reasons.append("trace status is error")
            if snapshot.errors:
                reasons.append(f"{len(snapshot.errors)} error span(s) present")
            checks[health_label] = {
                "passed": False,
                "detail": "; ".join(reasons),
                # One line per actual error (name, message, when) -- without
                # this, only the summary above would ever reach the report,
                # since these errors all share this check's own resource
                # label and would otherwise be deduped out of the violations
                # list as "just restating the check". See PluginCheck docs.
                "detail_items": [
                    f"{err.name} ({err.type or 'error'}): {err.message or 'no message'}"
                    + (f" at {err.timestamp}" if err.timestamp else "")
                    for err in snapshot.errors
                ],
            }
        else:
            checks[health_label] = {"passed": True, "detail": f"status={snapshot.status}, no error spans"}

        javaservice_active = any(write.resource.split(".")[0] == "javaservice" for write in contract.output)
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

        passed, score = score_from_checks(checks)

        # Informational only -- added after scoring so it never affects
        # passed/score; see plugins/timing.py.
        error_spans = [span for span in snapshot.spans if span.success is False]
        error_ms = sum_duration_ms(error_spans)
        checks["error time"] = {
            "passed": True,
            "detail": (
                f"{fmt_ms(error_ms)} across {len(error_spans)} error(s)" if error_spans else "no errors"
            ),
        }

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=score,
            violations=violations,
            evidence={
                "status": snapshot.status,
                "error_count": len(snapshot.errors),
                "failed_tools": len(snapshot.tools_summary.failed),
                "checks": checks,
            },
        )
