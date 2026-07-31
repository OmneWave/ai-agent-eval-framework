import yaml

from wm_agents_validator.contracts.loader import load_contract


def test_load_contract_accepts_nameless_output_reference_with_no_registry_entry(tmp_path):
    # Policy-constrained output reference (page.<page>.<subtype>, no name segment)
    # must load successfully even though resources.page[].variable has no entry --
    # there's nothing to look up for this form, so _validate_references must not
    # raise for it.
    contract_data = {
        "workflow": "test_workflow",
        "contract_version": "1.0.0",
        "skills": {"required": []},
        "resources": {"page": [{"name": "PetTable"}]},  # no `variable:` entry at all
        "output": [{"resource": "page.PetTable.variable", "operation": "CREATE"}],
    }
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(contract_data), encoding="utf-8")

    contract = load_contract(contract_path)

    assert contract.output[0].resource == "page.PetTable.variable"
