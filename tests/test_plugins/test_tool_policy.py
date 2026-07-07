from wm_agents_validator.plugins.tool_policy import ToolPolicyPlugin


def test_tool_policy_passes_with_fixture(snapshot, contract):
    result = ToolPolicyPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    # Standard evidence["checks"] contract: one entry per resource, pass or
    # fail, so a clean pass still shows what was actually checked.
    assert set(result.evidence["checks"]) == {"apiservice", "variable", "widget"}
    for check in result.evidence["checks"].values():
        assert check["passed"] is True
        assert check["detail"]


def test_tool_policy_flags_missing_required_tool(snapshot, contract):
    snapshot.spans = [s for s in snapshot.spans if s.name != "read_files"]
    snapshot.tools_summary.called = [t for t in snapshot.tools_summary.called if t != "read_files"]

    result = ToolPolicyPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "required_tool_missing" in codes

    checks = result.evidence["checks"]
    assert checks["apiservice"]["passed"] is False
    assert "read_files" in checks["apiservice"]["detail"]
    assert checks["variable"]["passed"] is True

    violation = next(v for v in result.violations if v.code == "required_tool_missing")
    assert violation.resource == "apiservice"


def test_tool_policy_flags_forbidden_tool_used(snapshot, contract):
    from wm_agents_validator.models.trace_snapshot import SpanRecord

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
            input={"file_path": "services/petstore/designtime/petstore_API_REST_SERVICE.json"},
            output=None,
            success=True,
        )
    )

    result = ToolPolicyPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "forbidden_tool_used" in codes

    checks = result.evidence["checks"]
    assert checks["apiservice"]["passed"] is False
    assert "delete_file" in checks["apiservice"]["detail"]
