from pathlib import Path

import yaml

from wm_agents_validator.models.workflow_contract import WorkflowContract


def load_contract(path: str | Path) -> WorkflowContract:
    contract_path = Path(path)
    with contract_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Contract must be a YAML mapping: {contract_path}")
    contract = WorkflowContract.model_validate(data)
    _validate_references(contract, contract_path)
    return contract


def _validate_references(contract: WorkflowContract, contract_path: Path) -> None:
    """Resolve every resource reference at load time, so a typo'd reference
    fails fast here instead of deep inside a plugin."""
    for entry in contract.input_context:
        _resolve_or_raise(contract, entry.resource, contract_path)
    for entry in contract.output:
        _resolve_or_raise(contract, entry.resource, contract_path)


def _resolve_or_raise(contract: WorkflowContract, ref: str, contract_path: Path) -> None:
    try:
        contract.resources.resolve(ref)
    except KeyError as exc:
        raise ValueError(f"{contract_path}: {exc}") from exc
