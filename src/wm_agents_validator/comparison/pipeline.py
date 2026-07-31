"""Orchestrates: discover trace IDs -> verify each -> aggregate -> (optionally) filter.

`ComparisonPipeline` depends only on the `TraceSource` protocol and an
injectable `evaluate` callable (Dependency Inversion), never on a concrete
fetch/HTTP implementation. That's what makes it unit-testable without network
access and swappable (e.g. a future `TraceSource` that reads from a local
cache).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from wm_agents_validator.comparison.aggregator import TraceOutcome, build_comparison_report
from wm_agents_validator.comparison.sources import TraceSource
from wm_agents_validator.controller.verify import VerifyResult, run_verification
from wm_agents_validator.models.comparison import ComparisonReport
from wm_agents_validator.models.workflow_contract import WorkflowContract

EvaluateFn = Callable[[str], VerifyResult]


def _default_evaluator(
    contract: WorkflowContract, *, retries: int, delay_sec: float
) -> EvaluateFn:
    def evaluate(trace_id: str) -> VerifyResult:
        return run_verification(contract, trace_id=trace_id, retries=retries, delay_sec=delay_sec)

    return evaluate


@dataclass
class ComparisonPipeline:
    contract: WorkflowContract
    source: TraceSource
    user_id_key: str = "user_id"
    model_filter: str | None = None
    user_prompt_filter: str | None = None
    skill_name_filter: str | None = None
    retries: int = 12
    delay_sec: float = 1.0
    evaluate: EvaluateFn | None = None
    """Injectable override for tests; defaults to fetch+normalize+verify via Langfuse."""

    def build_report(self) -> ComparisonReport:
        evaluate = self.evaluate or _default_evaluator(
            self.contract, retries=self.retries, delay_sec=self.delay_sec
        )

        outcomes: list[TraceOutcome] = []
        for trace_id in self.source.get_trace_ids():
            try:
                result = evaluate(trace_id)
                outcomes.append(TraceOutcome(trace_id=trace_id, verify_result=result))
            except Exception as exc:  # noqa: BLE001 - one bad trace shouldn't kill the batch
                outcomes.append(TraceOutcome(trace_id=trace_id, error=str(exc)))

        report = build_comparison_report(
            self.contract.contract_id,
            outcomes,
            contract_name=self.contract.name,
            user_id_key=self.user_id_key,
            workflow=self.contract.workflow,
        )
        if self.model_filter:
            report = report.filtered_by_model(self.model_filter)
        if self.user_prompt_filter:
            report = report.filtered_by_user_prompt(self.user_prompt_filter)
        if self.skill_name_filter:
            report = report.filtered_by_skill_name(self.skill_name_filter)
        return report
