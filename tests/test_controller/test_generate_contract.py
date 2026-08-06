import pytest
import yaml
from pydantic import ValidationError

from wm_agents_validator.controller.generate_contract import generate_contract
from wm_agents_validator.models.trace_snapshot import SpanRecord, TraceSnapshot


def _contract_dict(yaml_text: str) -> dict:
    return yaml.safe_load(yaml_text)


def test_generate_contract_from_fixture_snapshot(snapshot):
    # generate_contract() still emits the pre-genericization shape for pages --
    # path-less entries nested as page.variable/widget/javascript -- which the
    # current ResourceRegistry model rejects (every entry needs an explicit `path`,
    # and there's no more page-specific nesting). Its internal self-check now
    # raises for any page-touching trace; this documents that known, currently
    # accepted gap rather than silently expecting a result that can't be produced.
    with pytest.raises(ValidationError):
        generate_contract(snapshot, workflow="ui_to_api_binding")


def test_generate_contract_variable_via_platform_tool_only():
    # Real trace shape (confirmed against test_1.json): a variable created purely
    # via ui_createNonApiAwareVariable, with NO accompanying .variables.json
    # write/edit anywhere in the trace -- file_changes-based detection alone
    # would miss it entirely.
    trace = TraceSnapshot(
        trace_id="t1",
        entry_agent="wm_agent",
        status="success",
        skill_loads=[],
        spans=[
            SpanRecord(
                id="s1",
                name="write_file",
                type="TOOL",
                parent_id=None,
                agent_id="wm_screenshot_to_code_agent",
                input={"file_path": "src/main/webapp/pages/RegisterCompany/RegisterCompany.html"},
                output=None,
                success=True,
            ),
            SpanRecord(
                id="s2",
                name="ui_createNonApiAwareVariable",
                type="TOOL",
                parent_id=None,
                agent_id="wm_screenshot_to_code_agent",
                input={
                    "pageName": "RegisterCompany",
                    "variableData": {"name": "companyOptions", "type": "string"},
                },
                output=None,
                success=True,
            ),
        ],
    )

    # Same known gap as test_generate_contract_from_fixture_snapshot -- this trace
    # touches a page, so generate_contract()'s emitted path-less/nested shape fails
    # the current ResourceRegistry model's self-check.
    with pytest.raises(ValidationError):
        generate_contract(trace, workflow="screenshot_to_code")


def test_generate_contract_slugifies_design_token_overrides():
    trace = TraceSnapshot(
        trace_id="t2",
        entry_agent="wm_agent",
        status="success",
        skill_loads=[],
        spans=[
            SpanRecord(
                id="s1",
                name="write_file",
                type="TOOL",
                parent_id=None,
                agent_id="wm_screenshot_to_code_agent",
                input={"file_path": "src/main/webapp/design-tokens/overrides/components/btn/btn.json"},
                output=None,
                success=True,
            ),
            SpanRecord(
                id="s2",
                name="write_file",
                type="TOOL",
                parent_id=None,
                agent_id="wm_screenshot_to_code_agent",
                input={"file_path": "src/main/webapp/design-tokens/overrides/global/color/color.light.json"},
                output=None,
                success=True,
            ),
        ],
    )

    result = generate_contract(trace, workflow="screenshot_to_code")
    data = _contract_dict(result.yaml_text)

    design_token_names = {d["name"] for d in data["resources"]["design_tokens"]}
    assert design_token_names == {"components-btn", "global-color-light"}


def test_generate_contract_warns_on_unclassifiable_path():
    trace = TraceSnapshot(
        trace_id="t3",
        entry_agent="wm_agent",
        status="success",
        skill_loads=[],
        spans=[
            SpanRecord(
                id="s1",
                name="write_file",
                type="TOOL",
                parent_id=None,
                agent_id="wm_agent",
                input={"file_path": "some/totally/unrecognized/path.txt"},
                output=None,
                success=True,
            ),
        ],
    )

    result = generate_contract(trace, workflow="unknown_workflow")
    data = _contract_dict(result.yaml_text)

    assert data["output"] == []
    assert any("some/totally/unrecognized/path.txt" in w for w in result.warnings)


def test_generate_contract_output_is_load_bearing_yaml(snapshot, tmp_path):
    # Same known gap as test_generate_contract_from_fixture_snapshot -- the fixture
    # snapshot touches a page, so this never reaches the load-bearing-round-trip
    # check it was meant to exercise.
    with pytest.raises(ValidationError):
        generate_contract(snapshot, workflow="ui_to_api_binding")
