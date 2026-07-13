from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.plugins.tool_calls import ToolCallsPlugin


def test_tool_calls_passes_with_fixture(snapshot, contract):
    result = ToolCallsPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    checks = result.evidence["checks"]
    assert set(checks) == set(contract.tools.required) | {"forbidden tools", "tool call time"}
    for check in checks.values():
        assert check["passed"] is True


def test_tool_calls_flags_missing_required_tool(snapshot, contract):
    snapshot.spans = [s for s in snapshot.spans if s.name != "read_files"]
    snapshot.tools_summary.called = [t for t in snapshot.tools_summary.called if t != "read_files"]

    result = ToolCallsPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "required_tool_missing" in codes

    checks = result.evidence["checks"]
    assert checks["read_files"]["passed"] is False
    assert checks["ui_createApiAwareVariable"]["passed"] is True


def test_tool_calls_flags_forbidden_tool_used(snapshot, contract):
    snapshot.spans.append(
        SpanRecord(
            id="span-forbidden-delete",
            name="delete_file",
            type="TOOL",
            parent_id="span-deleg-backend",
            agent_id="wm_backend_expert",
            timestamp="2026-01-01T10:00:06Z",
            end_time=None,
            level="DEFAULT",
            input={"file_path": "services/petstore/designtime/petstore_apiTarget.json"},
            output=None,
            success=True,
        )
    )
    snapshot.tools_summary.called.append("delete_file")

    result = ToolCallsPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "forbidden_tool_used" in codes

    checks = result.evidence["checks"]
    assert checks["forbidden tools"]["passed"] is False
    assert "delete_file" in checks["forbidden tools"]["detail"]
