from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.plugins.output import OutputPlugin

_VARIABLE = "page.PetTable.variable.pet_table_variable"
_WIDGET = "page.PetTable.widget.swagger_findPetsByTagsTable1"


def test_output_passes_with_fixture(snapshot, contract):
    result = OutputPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    checks = result.evidence["checks"]
    assert checks[_VARIABLE]["passed"] is True
    assert checks[_WIDGET]["passed"] is True
    assert checks["unrelated changes"] == {
        "passed": True,
        "detail": "no changes outside contract scope",
    }


def test_output_flags_operation_mismatch(snapshot, contract):
    # DELETE observed where CREATE was declared for the variable.
    for span in snapshot.spans:
        if span.id == "span-variable-write":
            span.name = "delete_file"

    result = OutputPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "output_operation_mismatch" in codes

    checks = result.evidence["checks"]
    assert checks[_VARIABLE]["passed"] is False
    violation = next(v for v in result.violations if v.code == "output_operation_mismatch")
    assert violation.resource == _VARIABLE


def test_output_flags_unrelated_file_changed(snapshot, contract):
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

    result = OutputPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "unrelated_file_changed" in codes

    checks = result.evidence["checks"]
    assert checks["unrelated changes"]["passed"] is False
    assert "OtherPage.html" in checks["unrelated changes"]["detail"]

    violation = next(v for v in result.violations if v.code == "unrelated_file_changed")
    assert violation.resource == "unrelated changes"


def test_output_never_referenced_resource_is_protected_via_unrelated_diff(snapshot, contract):
    # api.petstore is only ever referenced under input_context -- modifying
    # it should be caught as an unrelated change, with no separate
    # "protected" mechanism needed.
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

    result = OutputPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "unrelated_file_changed" in codes
    assert "petstore_API_REST_SERVICE.json" in result.evidence["checks"]["unrelated changes"]["detail"]
