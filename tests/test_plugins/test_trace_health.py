from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.plugins.trace_health import TraceHealthPlugin


def test_trace_health_passes_with_fixture(snapshot, contract):
    result = TraceHealthPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    # Standard evidence["checks"] contract: "trace health" (status + error
    # spans, merged -- see below) is always checked; "build" only shows up
    # when javaservice is an active resource (this contract has none), so a
    # clean pass still shows what was actually verified.
    assert result.evidence["checks"] == {
        "trace health": {"passed": True, "detail": f"status={snapshot.status}, no error spans"},
        "error time": {"passed": True, "detail": "no errors"},
    }


def test_trace_health_flags_error_status(snapshot, contract):
    snapshot.status = "error"

    result = TraceHealthPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "trace_error_status" in codes
    assert result.evidence["checks"]["trace health"]["passed"] is False

    violation = next(v for v in result.violations if v.code == "trace_error_status")
    assert violation.resource == "trace health"


def test_trace_health_flags_error_spans(snapshot, contract):
    # `errors` is derived from spans (level="ERROR" or a failed TOOL span),
    # not a settable list -- add a span that produces one.
    snapshot.spans.append(
        SpanRecord(
            id="span-validation-error",
            name="validation_error",
            type="TOOL",
            parent_id="span-deleg-ui",
            agent_id="wm_ui_expert",
            timestamp="2026-01-01T10:00:14Z",
            end_time=None,
            level="ERROR",
            input={},
            output=None,
            success=False,
            error_message="bad input",
        )
    )

    result = TraceHealthPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "trace_error_span" in codes
    assert result.evidence["checks"]["trace health"]["passed"] is False
    assert "1 error span" in result.evidence["checks"]["trace health"]["detail"]

    violation = next(v for v in result.violations if v.code == "trace_error_span")
    assert violation.resource == "trace health"

    # The per-error breakdown (name/message/timestamp) must survive into the
    # check's detail_items, not just the generic count -- this is what the
    # report's chevron disclosure renders.
    detail_items = result.evidence["checks"]["trace health"]["detail_items"]
    assert len(detail_items) == 1
    assert "validation_error" in detail_items[0]
    assert "bad input" in detail_items[0]
    assert "2026-01-01T10:00:14Z" in detail_items[0]


def test_trace_health_reports_one_detail_item_per_error(snapshot, contract):
    for i in range(2):
        snapshot.spans.append(
            SpanRecord(
                id=f"span-error-{i}",
                name=f"tool_{i}",
                type="TOOL",
                timestamp="2026-01-01T10:00:14Z",
                success=False,
                error_message=f"failure {i}",
            )
        )

    result = TraceHealthPlugin().evaluate(snapshot, contract)

    detail_items = result.evidence["checks"]["trace health"]["detail_items"]
    assert len(detail_items) == 2
    assert any("failure 0" in item for item in detail_items)
    assert any("failure 1" in item for item in detail_items)


def test_trace_health_does_not_double_count_one_tool_failure_as_two_checks(snapshot, contract):
    # Regression: a single failed tool call (even if retried and later
    # recovered) makes both TraceSnapshot.status == "error" (_derive_status
    # treats any failed tool as reason enough) and TraceSnapshot.errors
    # non-empty (the same failed span, walked directly) -- the same root
    # cause. Scoring these as two separate checks meant one transient,
    # recoverable tool failure could zero out this plugin's score entirely
    # (0/2), even when nothing else was wrong. They must merge into one
    # check, so a single failure only ever costs one check, not two.
    snapshot.status = "error"
    snapshot.spans.append(
        SpanRecord(
            id="span-transient-failure",
            name="write_file",
            type="TOOL",
            timestamp="2026-01-01T10:00:14Z",
            success=False,
            error_message="Component folder does not exist",
        )
    )

    result = TraceHealthPlugin().evaluate(snapshot, contract)

    # Exactly one check represents this (no javaservice output on this
    # contract, so "build" never appears; "error time" is informational,
    # added after scoring) -- failing it gives 0%, same as before, but it's
    # one real check, not two counted against a single fact.
    assert set(result.evidence["checks"].keys()) == {"trace health", "error time"}
    assert result.score == 0.0
    codes = [v.code for v in result.violations]
    assert codes.count("trace_error_status") == 1
    assert codes.count("trace_error_span") == 1
