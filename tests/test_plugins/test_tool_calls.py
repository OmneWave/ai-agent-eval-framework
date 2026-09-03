from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.plugins.tool_calls import ToolCallsPlugin


def test_tool_calls_passes_with_fixture(snapshot, contract):
    result = ToolCallsPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    checks = result.evidence["checks"]
    assert set(checks) == set(contract.tools.required) | {"forbidden tools", "unrelated tools", "tool call time"}
    for check in checks.values():
        assert check["passed"] is True


def test_tool_calls_ignores_skill_and_delegation_tools_for_unrelated_check(snapshot, contract):
    # load_skill/start_new_conversation_with_agent are framework mechanics
    # (checked by SkillsLoadedPlugin/delegation tracking elsewhere), not
    # domain tools -- no contract declares them, and they shouldn't be
    # flagged as unrelated just because they're absent from tools.required.
    assert "load_skill" not in contract.tools.required
    assert "start_new_conversation_with_agent" not in contract.tools.required
    result = ToolCallsPlugin().evaluate(snapshot, contract)
    assert result.evidence["unrelated_tools"] == []
    assert result.evidence["checks"]["unrelated tools"]["passed"] is True


def test_tool_calls_flags_unrelated_tool_called(snapshot, contract):
    snapshot.spans.append(
        SpanRecord(
            id="span-unrelated-tool",
            name="platform_getAllPageNames",
            type="TOOL",
            parent_id="span-deleg-backend",
            agent_id="wm_backend_expert",
            timestamp="2026-01-01T10:00:06Z",
            end_time=None,
            level="DEFAULT",
            input={},
            output=None,
            success=True,
        )
    )
    snapshot.tools_summary.called.append("platform_getAllPageNames")

    result = ToolCallsPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "unrelated_tool_called" in codes
    assert result.evidence["unrelated_tools"] == ["platform_getAllPageNames"]
    assert result.evidence["checks"]["unrelated tools"]["passed"] is False


def test_tool_calls_does_not_enforce_unrelated_when_policy_fully_empty(snapshot, contract):
    bare_contract = contract.model_copy(update={"tools": contract.tools.model_copy(
        update={"required": [], "optional": [], "forbidden": []}
    )})
    snapshot.spans.append(
        SpanRecord(
            id="span-unrelated-tool",
            name="platform_getAllPageNames",
            type="TOOL",
            parent_id="span-deleg-backend",
            agent_id="wm_backend_expert",
            timestamp="2026-01-01T10:00:06Z",
            end_time=None,
            level="DEFAULT",
            input={},
            output=None,
            success=True,
        )
    )
    snapshot.tools_summary.called.append("platform_getAllPageNames")

    result = ToolCallsPlugin().evaluate(snapshot, bare_contract)

    check = result.evidence["checks"]["unrelated tools"]
    assert check["passed"] is True
    assert "not enforced" in check["detail"]
    assert "platform_getAllPageNames" in result.evidence["unrelated_tools"]


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
