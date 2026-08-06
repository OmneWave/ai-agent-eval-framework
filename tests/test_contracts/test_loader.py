import pytest
import yaml

from wm_agents_validator.contracts.loader import load_contract


def test_load_contract_accepts_any_registered_resource_type(tmp_path):
    # `resources:` isn't limited to a fixed set of type keys -- a brand-new type
    # name (registered with an explicit `path`) must load and resolve cleanly.
    contract_data = {
        "workflow": "test_workflow",
        "contract_version": "1.0.0",
        "skills": {"required": []},
        "resources": {"webhook": [{"name": "orderPlaced", "path": "services/hooks/orderPlaced.json"}]},
        "output": [{"resource": "webhook.orderPlaced", "operation": "CREATE"}],
    }
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(contract_data), encoding="utf-8")

    contract = load_contract(contract_path)

    assert contract.output[0].resource == "webhook.orderPlaced"


def test_load_contract_rejects_reference_to_unregistered_resource(tmp_path):
    # A reference must resolve against an entry actually registered under
    # `resources:` -- a typo'd/unregistered reference must fail fast at load
    # time rather than deep inside a plugin.
    contract_data = {
        "workflow": "test_workflow",
        "contract_version": "1.0.0",
        "skills": {"required": []},
        "resources": {"webhook": [{"name": "orderPlaced", "path": "services/hooks/orderPlaced.json"}]},
        "output": [{"resource": "webhook.orderShipped", "operation": "CREATE"}],
    }
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.dump(contract_data), encoding="utf-8")

    with pytest.raises(ValueError):
        load_contract(contract_path)
