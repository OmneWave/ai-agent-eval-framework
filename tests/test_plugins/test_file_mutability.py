from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.plugins.file_mutability import FileMutabilityPlugin


def test_file_mutability_passes_with_fixture(snapshot, contract):
    result = FileMutabilityPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    # Standard evidence["checks"] contract: one entry per resource that
    # declares a read_only file, plus a rollup "unrelated changes" check --
    # both shown even on a clean pass.
    assert result.evidence["checks"]["apiservice"] == {
        "passed": True,
        "detail": "read-only file(s) untouched",
    }
    assert result.evidence["checks"]["unrelated changes"] == {
        "passed": True,
        "detail": "no changes outside contract scope",
    }
    # variable/widget declare no read_only files, so they have nothing to
    # check here (tool_policy/context_grounding cover their own scope).
    assert "variable" not in result.evidence["checks"]
    assert "widget" not in result.evidence["checks"]


def test_file_mutability_flags_read_only_file_modified(snapshot, contract):
    snapshot.spans.append(
        SpanRecord(
            id="span-edit-readonly",
            name="edit_file_content",
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

    result = FileMutabilityPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "read_only_file_modified" in codes

    checks = result.evidence["checks"]
    assert checks["apiservice"]["passed"] is False
    assert "petstore_API_REST_SERVICE.json" in checks["apiservice"]["detail"]

    violation = next(v for v in result.violations if v.code == "read_only_file_modified")
    assert violation.resource == "apiservice"


def test_file_mutability_flags_unrelated_file_changed(snapshot, contract):
    snapshot.spans.append(
        SpanRecord(
            id="span-write-unrelated",
            name="write_file",
            type="TOOL",
            parent_id="span-deleg-ui",
            agent_id="wm_ui_expert",
            timestamp="2026-01-01T10:00:13Z",
            end_time=None,
            level="DEFAULT",
            input={"file_path": "src/main/webapp/pages/OtherPage/OtherPage.html"},
            output=None,
            success=True,
        )
    )

    result = FileMutabilityPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "unrelated_file_changed" in codes

    checks = result.evidence["checks"]
    assert checks["unrelated changes"]["passed"] is False
    assert "OtherPage.html" in checks["unrelated changes"]["detail"]

    violation = next(v for v in result.violations if v.code == "unrelated_file_changed")
    assert violation.resource == "unrelated changes"
