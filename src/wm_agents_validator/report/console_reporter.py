from __future__ import annotations

import json
from pathlib import Path

from wm_agents_validator.models.plugin_result import PluginResult
from wm_agents_validator.models.verification import VerificationReport
from wm_agents_validator.report.colors import green, red, yellow


def write_json_report(report: VerificationReport, path: str | Path) -> None:
    out = Path(path)
    out.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _tier(passed: bool, score: float) -> str:
    """Three-tier status: red = failed, yellow = passed with warnings, green = clean pass."""
    if not passed:
        return "red"
    if score < 1.0:
        return "yellow"
    return "green"


def _paint(tier: str, text: str) -> str:
    return {"red": red, "yellow": yellow, "green": green}[tier](text)


def print_console_report(report: VerificationReport) -> None:
    overall_tier = _tier(report.passed, report.overall_score)
    status = "PASSED" if report.passed else "FAILED"
    print(f"\n=== Verification {_paint(overall_tier, status)} ===")
    print(f"Trace:    {report.trace_id}")
    print(f"Contract: {report.contract_id}")
    print(f"Score:    {_paint(overall_tier, f'{report.overall_score:.2%}')}")
    print("\n--- Plugin Results ---")
    for pr in report.plugin_results:
        _print_plugin_result(pr)
    if report.violations:
        violations_tier = "red" if not report.passed else "yellow"
        print(f"\n{_paint(violations_tier, f'Total violations: {len(report.violations)}')}")


def _print_plugin_result(pr: PluginResult) -> None:
    tier = _tier(pr.passed, pr.score)
    mark = "PASS" if pr.passed else "FAIL"
    print(f"  [{_paint(tier, mark)}] {pr.plugin}: score={pr.score:.2f}")

    # Plugins that evaluate several named things (resources, budgeted metrics,
    # ...) can populate the standard evidence["checks"] contract (see
    # PluginResult docs) to report each one's outcome. Print those regardless
    # of pass/fail so a clean pass still shows *what* was checked, not just a
    # bare score.
    checks = pr.evidence.get("checks")
    covered_labels: set[str] = set()
    if isinstance(checks, dict):
        for label, info in checks.items():
            if not isinstance(info, dict):
                continue
            covered_labels.add(label)
            check_passed = bool(info.get("passed", True))
            check_tier = "green" if check_passed else tier
            check_mark = "OK" if check_passed else "WARN"
            detail = info.get("detail", "")
            print(f"         [{_paint(check_tier, check_mark)}] {label}: {detail}")

    for v in pr.violations:
        # Already reflected in the check line above; avoid printing it twice.
        if v.resource and v.resource in covered_labels:
            continue
        print(f"         - {_paint(tier, f'{v.code}: {v.message}')}")
