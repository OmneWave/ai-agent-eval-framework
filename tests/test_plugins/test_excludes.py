from wm_agents_validator.models.trace_snapshot import SpanRecord, TraceSnapshot
from wm_agents_validator.plugins.excludes import drop_excluded_spans, is_excluded_path
from wm_agents_validator.plugins.runner import run_plugins


def _span(span_id: str, name: str, tool_input: dict) -> SpanRecord:
    return SpanRecord(
        id=span_id, name=name, type="TOOL", parent_id=None, agent_id="a", input=tool_input, output=None, success=True
    )


def test_is_excluded_path():
    assert is_excluded_path("/notes/plan.md")
    assert is_excluded_path("notes/plan.md")
    assert is_excluded_path("/proj/notes/sub/plan.md")
    assert not is_excluded_path("src/main/webapp/pages/Login/Login.html")
    assert not is_excluded_path("src/notes.md")
    assert not is_excluded_path("/notes")


def test_drop_excluded_spans_removes_notes_only_calls_and_keeps_the_rest(snapshot):
    notes_write = _span("n1", "write_file", {"file_path": "/notes/plan.md"})
    notes_read = _span("n2", "read_files", {"paths": ["/notes/plan.md"]})
    mixed_read = _span("m1", "read_files", {"paths": ["/notes/plan.md", "src/a.html"]})
    trace = snapshot.model_copy(update={"spans": [notes_write, notes_read, mixed_read]})

    kept = drop_excluded_spans(trace)

    assert [s.id for s in kept.spans] == ["m1"]
    assert not any(fc.path.startswith("/notes/") for fc in kept.file_changes)


def test_run_plugins_does_not_flag_notes_as_unrelated(snapshot, contract):
    baseline = run_plugins(snapshot, contract)
    with_notes = snapshot.model_copy(
        update={
            "spans": [
                *snapshot.spans,
                _span("n1", "write_file", {"file_path": "/notes/plan.md"}),
                _span("n2", "read_files", {"paths": ["/notes/plan.md"]}),
            ]
        }
    )

    report = run_plugins(with_notes, contract)

    assert report.passed == baseline.passed
    assert not any("notes" in str(v.evidence) for v in report.violations)


def test_trace_health_still_sees_failed_notes_call(snapshot, contract):
    failed = _span("n1", "write_file", {"file_path": "/notes/plan.md"}).model_copy(update={"success": False, "level": "ERROR"})
    trace = snapshot.model_copy(update={"spans": [*snapshot.spans, failed]})

    health = next(r for r in run_plugins(trace, contract).plugin_results if r.plugin == "trace_health")
    baseline = next(r for r in run_plugins(snapshot, contract).plugin_results if r.plugin == "trace_health")

    assert len(health.violations) > len(baseline.violations) or health.score < baseline.score


def test_spawn_and_fork_stay_in_trace_but_are_not_scored(snapshot, contract):
    spawn = _span("s1", "spawn", {"agent": "x"})
    fork = _span("s2", "fork", {"agent": "y"})
    trace = snapshot.model_copy(
        update={
            "spans": [*snapshot.spans, spawn, fork],
            "tools_summary": snapshot.tools_summary.model_copy(
                update={"called": [*snapshot.tools_summary.called, "spawn", "fork"]}
            ),
        }
    )

    report = run_plugins(trace, contract)
    tool_calls = next(r for r in report.plugin_results if r.plugin == "tool_calls")

    assert {"spawn", "fork"} <= set(trace.tool_names)
    assert {s.name for s in trace.spans} >= {"spawn", "fork"}
    assert tool_calls.evidence["unrelated_tools"] == []
    assert not any("spawn" in str(v.evidence) or "fork" in str(v.evidence) for v in tool_calls.violations)
    assert tool_calls.evidence["unscored_tools"] == ["spawn", "fork"]
