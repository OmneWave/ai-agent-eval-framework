import yaml

from wm_agents_validator.controller.generate_contract import generate_contract
from wm_agents_validator.models.trace_snapshot import SpanRecord, TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


def _contract_dict(yaml_text: str) -> dict:
    return yaml.safe_load(yaml_text)


def test_generate_contract_from_fixture_snapshot(snapshot):
    result = generate_contract(snapshot, workflow="ui_to_api_binding")
    data = _contract_dict(result.yaml_text)
    contract = WorkflowContract.model_validate(data)

    page = next(e for e in contract.resources.page if e.name == "PetTable")
    assert page.path == "src/main/webapp/pages/PetTable/PetTable.html"
    assert page.variable[0].path == "src/main/webapp/pages/PetTable/PetTable.variables.json"
    assert page.javascript[0].path == "src/main/webapp/pages/PetTable/PetTable.js"

    output_refs = {e.resource for e in contract.output if hasattr(e, "resource")}
    assert "page.PetTable" in output_refs
    assert any(ref.startswith("page.PetTable.variable.") for ref in output_refs)
    assert any(ref.startswith("page.PetTable.javascript.") for ref in output_refs)

    for entry in contract.output:
        if hasattr(entry, "resource"):
            contract.resources.resolve(entry.resource)


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

    result = generate_contract(trace, workflow="screenshot_to_code")
    data = _contract_dict(result.yaml_text)
    contract = WorkflowContract.model_validate(data)

    page = next(e for e in contract.resources.page if e.name == "RegisterCompany")
    assert page.variable[0].name == "companyOptions"
    assert page.variable[0].path == "src/main/webapp/pages/RegisterCompany/RegisterCompany.variables.json"

    output_refs = {e.resource for e in contract.output if hasattr(e, "resource")}
    assert "page.RegisterCompany.variable.companyOptions" in output_refs
    contract.resources.resolve("page.RegisterCompany.variable.companyOptions")


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
    result = generate_contract(snapshot, workflow="ui_to_api_binding")
    out_file = tmp_path / "generated.yaml"
    out_file.write_text(result.yaml_text, encoding="utf-8")

    data = yaml.safe_load(out_file.read_text(encoding="utf-8"))
    contract = WorkflowContract.model_validate(data)
    for entry in contract.output:
        if hasattr(entry, "resource"):
            contract.resources.resolve(entry.resource)


def test_generate_contract_emits_tool_check_for_pathless_mutation():
    # ui_applyChangesOnPageMarkup edits inline markup with no separate file
    # written -- it can't become a path-based WriteSpec, so it should surface as
    # a standalone ToolCheck (tool + match) output entry instead of only being
    # listed flatly in tools.required.
    trace = TraceSnapshot(
        trace_id="t4",
        entry_agent="wm_agent",
        status="success",
        skill_loads=[],
        spans=[
            SpanRecord(
                id="s1",
                name="execute_tool",
                type="TOOL",
                parent_id=None,
                agent_id="wm_agent",
                input={
                    "tool_name": "ui_applyChangesOnPageMarkup",
                    "tool_args": {"pageName": "PetTable", "change": "replace"},
                },
                output=None,
                success=True,
            ),
        ],
    )

    result = generate_contract(trace, workflow="ui_to_api_binding")
    data = _contract_dict(result.yaml_text)
    contract = WorkflowContract.model_validate(data)

    tool_checks = [e for e in contract.output if hasattr(e, "tool")]
    assert len(tool_checks) == 1
    assert tool_checks[0].tool == "execute_tool.ui_applyChangesOnPageMarkup"
    assert tool_checks[0].match[0].fields == {"pageName": "PetTable"}
