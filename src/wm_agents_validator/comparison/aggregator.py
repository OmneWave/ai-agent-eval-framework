"""Turns per-trace verification outcomes into a `ComparisonReport`.

Single responsibility: pure data transformation, no I/O. This keeps it trivial
to unit-test and reusable regardless of how traces were fetched or how the
report will be rendered.
"""
from __future__ import annotations

from dataclasses import dataclass

from wm_agents_validator.controller.verify import VerifyResult
from wm_agents_validator.models.comparison import (
    ComparisonReport,
    ComparisonRow,
    GenerationSummary,
    PluginCheck,
    PluginScore,
    PluginViolation,
    unique_in_order,
)
from wm_agents_validator.trace.screenshots import (
    extract_input_screenshot,
    extract_output_screenshot,
)


def _extract_checks(evidence: dict) -> list[PluginCheck]:
    """Reads the standard ``evidence["checks"]`` contract (see `PluginResult`
    docs) that any plugin can populate to report a full pass/fail breakdown of
    the named things it evaluated. This is driven entirely by that shape, not
    by plugin name, so any current or future plugin adopting the contract gets
    checks in the comparison UI/console for free.
    """
    checks = evidence.get("checks")
    if not isinstance(checks, dict):
        return []
    result: list[PluginCheck] = []
    for label, info in checks.items():
        if not isinstance(info, dict):
            continue
        detail_items = info.get("detail_items")
        result.append(
            PluginCheck(
                label=str(label),
                passed=bool(info.get("passed", True)),
                detail=str(info.get("detail") or ""),
                detail_items=[str(item) for item in detail_items] if isinstance(detail_items, list) else [],
            )
        )
    return result


@dataclass
class TraceOutcome:
    """Result of attempting to fetch + verify a single trace."""

    trace_id: str
    verify_result: VerifyResult | None = None
    error: str | None = None


def _row_from_success(
    outcome: TraceOutcome, *, contract_id: str, contract_name: str | None, user_id_key: str, is_screenshot_workflow: bool = False
) -> ComparisonRow:
    assert outcome.verify_result is not None
    snapshot = outcome.verify_result.snapshot
    report = outcome.verify_result.report
    payload = outcome.verify_result.payload

    input_screenshot: str | None = None
    output_screenshot: str | None = None
    if is_screenshot_workflow:
        input_screenshot = extract_input_screenshot(snapshot, payload)
        output_screenshot = extract_output_screenshot(snapshot, payload)

    plugin_scores = [
        PluginScore(
            plugin=result.plugin,
            passed=result.passed,
            score=result.score,
            violations=[
                PluginViolation(code=v.code, message=v.message, resource=v.resource)
                for v in result.violations
            ],
            checks=_extract_checks(result.evidence),
        )
        for result in report.plugin_results
    ]
    generations = [
        GenerationSummary(
            name=g.name,
            agent_id=g.agent_id,
            total_tokens=g.total_tokens,
            cost_usd=g.cost_usd,
        )
        for g in snapshot.generations
    ]
    skill_names = [name for load in snapshot.skill_loads for name in load.skill_names]

    return ComparisonRow(
        trace_id=outcome.trace_id,
        status="ok",
        contract_id=contract_id,
        contract_name=contract_name,
        model_name=snapshot.metadata.get("model_name"),
        user_id=snapshot.metadata.get(user_id_key),
        entry_agent=snapshot.entry_agent,
        session_id=snapshot.session_id,
        user_prompt=snapshot.user_prompt,
        skill_names=skill_names,
        duration_ms=snapshot.duration_ms,
        total_tokens=snapshot.total_tokens,
        total_cost_usd=snapshot.total_cost_usd,
        overall_score=report.overall_score,
        passed=report.passed,
        input_screenshot=input_screenshot,
        output_screenshot=output_screenshot,
        plugin_scores=plugin_scores,
        generations=generations,
    )


def _row_from_error(outcome: TraceOutcome, *, contract_id: str, contract_name: str | None) -> ComparisonRow:
    return ComparisonRow(
        trace_id=outcome.trace_id,
        status="error",
        contract_id=contract_id,
        contract_name=contract_name,
        error_message=outcome.error or "unknown error",
    )


def build_comparison_report(
    contract_id: str,
    outcomes: list[TraceOutcome],
    *,
    contract_name: str | None = None,
    user_id_key: str = "user_id",
    workflow: str = "",
) -> ComparisonReport:
    is_screenshot = workflow.startswith("screenshot_to_code")
    rows = [
        _row_from_success(
            outcome, contract_id=contract_id, contract_name=contract_name, user_id_key=user_id_key, is_screenshot_workflow=is_screenshot
        )
        if outcome.verify_result is not None
        else _row_from_error(outcome, contract_id=contract_id, contract_name=contract_name)
        for outcome in outcomes
    ]
    return ComparisonReport(contract_id=contract_id, rows=rows)


def merge_reports(reports: list[ComparisonReport]) -> ComparisonReport:
    """Combines reports from several `ComparisonPipeline` runs (e.g. one per
    contract) into a single report for one HTML render.
    """
    if not reports:
        raise ValueError("reports must be a non-empty list")

    rows = [row for report in reports for row in report.rows]
    contract_ids = unique_in_order(r.contract_id for r in reports)
    label = contract_ids[0] if len(contract_ids) == 1 else ", ".join(contract_ids)
    return ComparisonReport(contract_id=label, rows=rows)
