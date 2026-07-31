import yaml

from wm_agents_validator.controller.generate_contract import generate_contract
from wm_agents_validator.models.trace_snapshot import SpanRecord, TraceSnapshot


def _contract_dict(yaml_text: str) -> dict:
    return yaml.safe_load(yaml_text)


def test_generate_contract_from_fixture_snapshot(snapshot):
    result = generate_contract(snapshot, workflow="ui_to_api_binding")
    data = _contract_dict(result.yaml_text)

    assert data["workflow"] == "ui_to_api_binding"
    assert data["contract_version"] == "1.0.0"

    page_names = {p["name"] for p in data["resources"]["page"]}
    assert page_names == {"PetTable"}

    api_names = {a["name"] for a in data["resources"]["api"]}
    assert "petstore" in api_names

    output_refs = {entry["resource"] for entry in data["output"]}
    assert "page.PetTable" in output_refs
    assert "page.PetTable.variable" in output_refs
    assert "page.PetTable.javascript" in output_refs

    variable_entry = next(e for e in data["output"] if e["resource"] == "page.PetTable.variable")
    # The fixture's ui_createApiAwareVariable call now also synthesizes a
    # "write" FileChangeRecord for this path (see TraceSnapshot.file_changes),
    # so CREATE wins even though the file itself only saw an `edit_file_content`
    # call directly.
    assert variable_entry["operation"] == "CREATE"
    # The fixture's platform-tool call carries operationId, so `match` should
    # be populated, not left empty.
    assert variable_entry.get("match") == {"operationId": "petstore_findPetsByTags"}

    input_refs = {entry["resource"] for entry in data["input_context"]}
    assert "api.petstore" in input_refs


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

    output_refs = {entry["resource"] for entry in data["output"]}
    assert "page.RegisterCompany.variable" in output_refs

    variable_entry = next(e for e in data["output"] if e["resource"] == "page.RegisterCompany.variable")
    assert variable_entry["operation"] == "CREATE"
    assert variable_entry.get("match") == ["companyOptions"]


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
    # The generator self-checks internally, but confirm the round trip through
    # the real loader too (extra="forbid" models catch any stray/misnamed field).
    from wm_agents_validator.contracts.loader import load_contract

    result = generate_contract(snapshot, workflow="ui_to_api_binding")
    path = tmp_path / "generated.yaml"
    path.write_text(result.yaml_text, encoding="utf-8")
    loaded = load_contract(path)
    assert loaded.workflow == "ui_to_api_binding"
