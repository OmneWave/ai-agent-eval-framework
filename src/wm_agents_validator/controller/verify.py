from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wm_agents_validator.contracts.loader import load_contract
from wm_agents_validator.models.plugin_result import EvalContext
from wm_agents_validator.models.raw_trace import RawTracePayload
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.verification import VerificationReport
from wm_agents_validator.models.workflow_contract import WorkflowContract
from wm_agents_validator.plugins.runner import run_plugins
from wm_agents_validator.controller.fetch import fetch_and_normalize


@dataclass
class VerifyResult:
    report: VerificationReport
    snapshot: TraceSnapshot
    payload: RawTracePayload | None = None


def load_snapshot(path: str | Path) -> TraceSnapshot:
    return TraceSnapshot.model_validate_json(Path(path).read_text(encoding="utf-8"))


def run_verification(
    contract: WorkflowContract | str,
    *,
    snapshot: TraceSnapshot | None = None,
    trace_id: str | None = None,
    context: EvalContext | None = None,
    plugins: list[str] | None = None,
    retries: int = 12,
    delay_sec: float = 1.0,
) -> VerifyResult:
    if isinstance(contract, str):
        contract = load_contract(contract)

    context = context or EvalContext()

    if snapshot is None:
        if not trace_id:
            raise ValueError("trace_id is required when snapshot is not provided")
        fetch_result = fetch_and_normalize(
            trace_id,
            retries=retries,
            delay_sec=delay_sec,
        )
        snapshot = fetch_result.snapshot
        payload = fetch_result.payload
    else:
        payload = None

    report = run_plugins(snapshot, contract, plugins=plugins, context=context)
    return VerifyResult(report=report, snapshot=snapshot, payload=payload)
