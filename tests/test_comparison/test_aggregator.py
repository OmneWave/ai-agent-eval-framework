from wm_agents_validator.comparison.aggregator import TraceOutcome, build_comparison_report
from wm_agents_validator.controller.verify import VerifyResult
from wm_agents_validator.models.plugin_result import PluginResult, Violation
from wm_agents_validator.models.verification import VerificationReport


def _verify_result(snapshot, *, passed=True, score=1.0):
    report = VerificationReport(
        trace_id=snapshot.trace_id,
        contract_id="test-contract",
        passed=passed,
        overall_score=score,
        plugin_results=[
            PluginResult(plugin="intent_verification", passed=True, score=1.0),
            PluginResult(
                plugin="context_grounding",
                passed=passed,
                score=score,
                violations=[
                    Violation(
                        code="context_path_not_retrieved",
                        message="missing path",
                        plugin="context_grounding",
                    )
                ],
            ),
        ],
        violations=[
            Violation(
                code="context_path_not_retrieved",
                message="missing path",
                plugin="context_grounding",
            )
        ]
        if not passed
        else [],
    )
    return VerifyResult(report=report, snapshot=snapshot)


def test_build_comparison_report_success_row_captures_metrics(snapshot):
    snapshot.metadata["model_name"] = "gpt-4"
    snapshot.metadata["user_id"] = "alice"
    outcome = TraceOutcome(trace_id=snapshot.trace_id, verify_result=_verify_result(snapshot))

    report = build_comparison_report("test-contract", [outcome])

    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.status == "ok"
    assert row.contract_id == "test-contract"
    assert row.model_name == "gpt-4"
    assert row.user_id == "alice"
    assert row.overall_score == 1.0
    assert row.passed is True
    assert {p.plugin for p in row.plugin_scores} == {"intent_verification", "context_grounding"}


def test_build_comparison_report_uses_custom_user_id_key(snapshot):
    snapshot.metadata["internal_uid"] = "user-42"
    outcome = TraceOutcome(trace_id=snapshot.trace_id, verify_result=_verify_result(snapshot))

    report = build_comparison_report("test-contract", [outcome], user_id_key="internal_uid")

    assert report.rows[0].user_id == "user-42"


def test_build_comparison_report_captures_violations_and_failure(snapshot):
    outcome = TraceOutcome(
        trace_id=snapshot.trace_id, verify_result=_verify_result(snapshot, passed=False, score=0.5)
    )

    report = build_comparison_report("test-contract", [outcome])

    row = report.rows[0]
    assert row.passed is False
    assert row.violation_count == 1

    context_grounding = next(p for p in row.plugin_scores if p.plugin == "context_grounding")
    assert [v.code for v in context_grounding.violations] == ["context_path_not_retrieved"]
    assert context_grounding.violations[0].message == "missing path"

    intent_verification = next(p for p in row.plugin_scores if p.plugin == "intent_verification")
    assert intent_verification.violations == []


def test_build_comparison_report_error_row_for_failed_fetch():
    outcome = TraceOutcome(trace_id="broken-trace", error="Langfuse timeout")

    report = build_comparison_report("test-contract", [outcome])

    row = report.rows[0]
    assert row.status == "error"
    assert row.is_error
    assert row.error_message == "Langfuse timeout"
    assert row.overall_score is None
    assert row.contract_id == "test-contract"


def test_build_comparison_report_extracts_checks_when_passing(snapshot):
    # Plugins that populate the standard evidence["checks"] contract must
    # surface those as PluginCheck entries even when everything passes
    # cleanly (no violations to look at otherwise).
    report_obj = VerificationReport(
        trace_id=snapshot.trace_id,
        contract_id="test-contract",
        passed=True,
        overall_score=1.0,
        plugin_results=[
            PluginResult(
                plugin="context_grounding",
                passed=True,
                score=1.0,
                evidence={
                    "checks": {
                        "apiservice": {"passed": True, "detail": "context fully grounded"},
                        "widget": {"passed": True, "detail": "context fully grounded"},
                    }
                },
            ),
        ],
    )
    outcome = TraceOutcome(
        trace_id=snapshot.trace_id, verify_result=VerifyResult(report=report_obj, snapshot=snapshot)
    )

    report = build_comparison_report("test-contract", [outcome])

    context_grounding = report.rows[0].plugin_scores[0]
    assert context_grounding.violations == []
    assert {c.label: c.passed for c in context_grounding.checks} == {
        "apiservice": True,
        "widget": True,
    }
    assert all(c.detail == "context fully grounded" for c in context_grounding.checks)


def test_build_comparison_report_extracts_checks_when_failing(snapshot):
    report_obj = VerificationReport(
        trace_id=snapshot.trace_id,
        contract_id="test-contract",
        passed=False,
        overall_score=0.5,
        plugin_results=[
            PluginResult(
                plugin="context_grounding",
                passed=False,
                score=0.5,
                evidence={
                    "checks": {
                        "apiservice": {"passed": False, "detail": "expected file(s) never retrieved"},
                        "widget": {"passed": True, "detail": "context fully grounded"},
                    }
                },
            ),
        ],
    )
    outcome = TraceOutcome(
        trace_id=snapshot.trace_id, verify_result=VerifyResult(report=report_obj, snapshot=snapshot)
    )

    report = build_comparison_report("test-contract", [outcome])

    context_grounding = report.rows[0].plugin_scores[0]
    checks_by_label = {c.label: c for c in context_grounding.checks}
    assert checks_by_label["apiservice"].passed is False
    assert checks_by_label["apiservice"].detail == "expected file(s) never retrieved"
    assert checks_by_label["widget"].passed is True


def test_build_comparison_report_mixes_success_and_error_rows(snapshot):
    outcomes = [
        TraceOutcome(trace_id=snapshot.trace_id, verify_result=_verify_result(snapshot)),
        TraceOutcome(trace_id="broken-trace", error="boom"),
    ]

    report = build_comparison_report("test-contract", outcomes)

    assert report.contract_id == "test-contract"
    assert [r.status for r in report.rows] == ["ok", "error"]
