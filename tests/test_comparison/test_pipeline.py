from wm_agents_validator.comparison.pipeline import ComparisonPipeline
from wm_agents_validator.comparison.sources import ExplicitTraceIdSource
from wm_agents_validator.controller.verify import VerifyResult
from wm_agents_validator.models.verification import VerificationReport


def _make_verify_result(snapshot, trace_id, model_name, score=1.0, passed=True):
    clone = snapshot.model_copy(deep=True)
    clone.trace_id = trace_id
    clone.metadata = {**clone.metadata, "model_name": model_name}
    report = VerificationReport(
        trace_id=trace_id,
        contract_id="test-contract",
        passed=passed,
        overall_score=score,
    )
    return VerifyResult(report=report, snapshot=clone)


def test_pipeline_builds_report_using_injected_evaluator(snapshot, contract):
    results = {
        "trace-a": _make_verify_result(snapshot, "trace-a", "gpt-4"),
        "trace-b": _make_verify_result(snapshot, "trace-b", "claude"),
    }
    pipeline = ComparisonPipeline(
        contract=contract,
        source=ExplicitTraceIdSource(["trace-a", "trace-b"]),
        evaluate=lambda trace_id: results[trace_id],
    )

    report = pipeline.build_report()

    assert [r.trace_id for r in report.rows] == ["trace-a", "trace-b"]
    assert [r.model_name for r in report.rows] == ["gpt-4", "claude"]


def test_pipeline_applies_model_filter(snapshot, contract):
    results = {
        "trace-a": _make_verify_result(snapshot, "trace-a", "gpt-4"),
        "trace-b": _make_verify_result(snapshot, "trace-b", "claude"),
    }
    pipeline = ComparisonPipeline(
        contract=contract,
        source=ExplicitTraceIdSource(["trace-a", "trace-b"]),
        evaluate=lambda trace_id: results[trace_id],
        model_filter="claude",
    )

    report = pipeline.build_report()

    assert [r.trace_id for r in report.rows] == ["trace-b"]


def test_pipeline_keeps_going_when_one_trace_fails(snapshot, contract):
    def evaluate(trace_id: str):
        if trace_id == "bad-trace":
            raise RuntimeError("fetch failed: 404")
        return _make_verify_result(snapshot, trace_id, "gpt-4")

    pipeline = ComparisonPipeline(
        contract=contract,
        source=ExplicitTraceIdSource(["good-trace", "bad-trace"]),
        evaluate=evaluate,
    )

    report = pipeline.build_report()

    assert len(report.rows) == 2
    good, bad = report.rows
    assert good.status == "ok"
    assert bad.status == "error"
    assert "fetch failed" in bad.error_message
