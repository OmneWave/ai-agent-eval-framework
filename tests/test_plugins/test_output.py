from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.models.trace_snapshot import match_satisfied as _match_satisfied_clauses
from wm_agents_validator.models.workflow_contract import MatchClause, WriteSpec
from wm_agents_validator.plugins.output import OutputPlugin


def _match_satisfied(raw_match, tool_input):
    """Test helper: parse a raw dict/list/string match shape the same way
    ``HasMatchClauses``'s validator does, then evaluate it -- exercises the
    real ``MatchClause.parse`` + polymorphic ``satisfied()`` path."""
    clauses = [] if not raw_match else (
        [MatchClause.parse(raw_match)] if isinstance(raw_match, dict) else [MatchClause.parse(item) for item in raw_match]
    )
    return _match_satisfied_clauses(clauses, tool_input)

_VARIABLE = "page.PetTable.variable.findPetsByTagsVariable"
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


def test_output_reports_output_generation_time_without_affecting_score(snapshot, contract):
    result = OutputPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    time_check = result.evidence["checks"]["output generation time"]
    assert time_check["passed"] is True
    assert "call(s)" in time_check["detail"]


def test_output_flags_operation_mismatch(snapshot, contract):
    # DELETE observed where CREATE was declared for the variable. Also strip
    # every ui_create*/updateVariable call's path so none of them independently
    # synthesize a CREATE/UPDATE FileChangeRecord (see file_changes) that would
    # otherwise still satisfy the entry despite the file-level delete below.
    for span in snapshot.spans:
        if span.id == "span-variable-write":
            span.name = "delete_file"
        elif span.id in ("span-create-var", "span-update-var", "span-create-nonapi-var"):
            span.input = {k: v for k, v in span.input.items() if k not in ("path", "pageName", "file_path")}

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


def _variable_contract_with_match(contract, match):
    # Swap only the variable entry's `match` clause -- keep the widget/javascript
    # entries as-is, or the unrelated-file-changed check would flag their file
    # changes as no longer declared anywhere in `output`.
    updated_variable = WriteSpec(resource=_VARIABLE, operation="CREATE", match=match)
    new_output = [updated_variable] + [w for w in contract.output if w.resource != _VARIABLE]
    return contract.model_copy(update={"output": new_output})


def test_output_match_dict_form_matches_platform_tool_evidence(snapshot, contract):
    # The fixture's edit_file_content stand-in span ALSO carries operationId
    # today, which would let this pass without genuinely exercising the new
    # widened-evidence path -- strip it so only ui_createApiAwareVariable does.
    for span in snapshot.spans:
        if span.id == "span-variable-write":
            span.input = {k: v for k, v in span.input.items() if k != "operationId"}

    policy_contract = _variable_contract_with_match(contract, {"operationId": "petstore_findPetsByTags"})
    result = OutputPlugin().evaluate(snapshot, policy_contract)

    assert result.passed
    assert result.violations == []


def test_output_match_mismatch_reports_new_violation_code(snapshot, contract):
    policy_contract = _variable_contract_with_match(contract, {"operationId": "petstore_findPetsByOtherThing"})
    result = OutputPlugin().evaluate(snapshot, policy_contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "output_match_mismatch" in codes
    assert "output_operation_mismatch" not in codes  # operation itself WAS observed
    assert result.evidence["checks"][_VARIABLE]["passed"] is False


def test_output_match_list_form_matches_value_under_any_field(snapshot, contract):
    # List shape: value must appear under *some* field, without naming operationId.
    policy_contract = _variable_contract_with_match(contract, ["petstore_findPetsByTags"])
    result = OutputPlugin().evaluate(snapshot, policy_contract)

    assert result.passed
    assert result.violations == []


def test_output_match_ignores_read_tool_evidence(snapshot, contract):
    # A read_files call at the same path carrying the match value must NOT
    # satisfy `match` -- evidencing spans are restricted to write tools
    # (OUTPUT_GENERATION_TOOLS); a read is not evidence of what got written.
    for span in snapshot.spans:
        if span.id in ("span-create-var", "span-variable-write"):
            span.input = {k: v for k, v in span.input.items() if k != "operationId"}
    snapshot.spans.append(
        SpanRecord(
            id="span-read-variable-file",
            name="read_files",
            type="TOOL",
            parent_id="span-deleg-ui",
            agent_id="wm_ui_expert",
            timestamp="2026-01-01T10:00:10Z",
            end_time=None,
            level="DEFAULT",
            input={
                "paths": ["src/main/webapp/pages/PetTable/PetTable.variables.json"],
                "operationId": "petstore_findPetsByTags",
            },
            output=None,
            success=True,
        )
    )
    policy_contract = _variable_contract_with_match(contract, {"operationId": "petstore_findPetsByTags"})
    result = OutputPlugin().evaluate(snapshot, policy_contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "output_match_mismatch" in codes


def test_match_satisfied_dict_and_list_shapes():
    span_input = {"operationId": "petstore_findPetsByTags", "service": "petstore"}

    # dict shape
    assert _match_satisfied({"operationId": "petstore_findPetsByTags"}, span_input) is True
    assert _match_satisfied({"operationId": "wrong"}, span_input) is False
    assert _match_satisfied({"missingKey": "x"}, span_input) is False

    # list shape -- value under any field, case-insensitive
    assert _match_satisfied(["PETSTORE_FINDPETSBYTAGS"], span_input) is True
    assert _match_satisfied(["not_present_anywhere"], span_input) is False

    # list shape -- substring within a larger field value, e.g. a widget tag
    # buried inside write_file's file_content (not the field's *entire* value)
    content_input = {"file_path": "LoginPage.html", "file_content": "<div><wm-button name='b1'/></div>"}
    assert _match_satisfied(["button"], content_input) is True
    assert _match_satisfied(["textbox"], content_input) is False

    # empty -- no constraint
    assert _match_satisfied({}, span_input) is True
    assert _match_satisfied([], span_input) is True


def test_match_satisfied_regex_shape():
    span_input = {"operationId": "petstore_findPetsByTags", "action": "replace"}

    assert _match_satisfied([{"regex": "^petstore_.*Tags$", "field": "operationId"}], span_input) is True
    assert _match_satisfied([{"regex": "^wrong$", "field": "operationId"}], span_input) is False
    # no `field:` -- searches the whole stringified input
    assert _match_satisfied([{"regex": "findPetsBy"}], span_input) is True


def test_match_satisfied_mixed_clause_list_is_anded():
    span_input = {"operationId": "petstore_findPetsByTags", "pageName": "PetTable"}

    # one dict clause + one list-of-strings clause + one regex clause, all in
    # the same match list -- every clause must hold
    mixed = [
        {"pageName": "PetTable"},
        ["petstore_findPetsByTags"],
        {"regex": "^PetTable$", "field": "pageName"},
    ]
    assert _match_satisfied(mixed, span_input) is True

    # swap one clause to something false -- the whole thing fails
    broken = [{"pageName": "PetTable"}, ["not_present"], {"regex": "^PetTable$", "field": "pageName"}]
    assert _match_satisfied(broken, span_input) is False


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
            input={"file_path": "services/petstore/designtime/petstore_apiTarget.json"},
            output=None,
            success=True,
        )
    )

    result = OutputPlugin().evaluate(snapshot, contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "unrelated_file_changed" in codes
    assert "petstore_apiTarget.json" in result.evidence["checks"]["unrelated changes"]["detail"]
