from pathlib import Path

import yaml

from wm_agents_validator.models.workflow_contract import WorkflowContract


def load_contract(path: str | Path) -> WorkflowContract:
    contract_path = Path(path)
    with contract_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Contract must be a YAML mapping: {contract_path}")
    return WorkflowContract.model_validate(data)
