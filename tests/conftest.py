from pathlib import Path

import pytest

from wm_agents_validator.contracts.loader import load_contract
from wm_agents_validator.models.plugin_result import EvalContext
from wm_agents_validator.models.trace_snapshot import TraceSnapshot

FIXTURES = Path(__file__).parent / "fixtures"
CONTRACTS = Path(__file__).parent.parent / "contracts"


@pytest.fixture
def snapshot() -> TraceSnapshot:
    return TraceSnapshot.model_validate_json(
        (FIXTURES / "trace_snapshot.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def contract():
    return load_contract(CONTRACTS / "binding" / "binding_with_widget.yaml")


@pytest.fixture
def context() -> EvalContext:
    return EvalContext(bindings={"page": "UserPage", "serviceId": "UserService"})
