from __future__ import annotations

import json
from pathlib import Path

from wm_agents_validator.models.verification import VerificationReport


def write_json_report(report: VerificationReport, path: str | Path) -> None:
    out = Path(path)
    out.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def print_console_report(report: VerificationReport) -> None:
    status = "PASSED" if report.passed else "FAILED"
    print(f"\n=== Verification {status} ===")
    print(f"Trace:    {report.trace_id}")
    print(f"Contract: {report.contract_id}")
    print(f"Score:    {report.overall_score:.2%}")
    print("\n--- Plugin Results ---")
    for pr in report.plugin_results:
        mark = "PASS" if pr.passed else "FAIL"
        print(f"  [{mark}] {pr.plugin}: score={pr.score:.2f}")
        for v in pr.violations:
            print(f"         - {v.code}: {v.message}")
    if report.blocking_checks:
        print("\n--- Blocking Checks ---")
        for check, ok in report.blocking_checks.items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {check}")
    if report.violations:
        print(f"\nTotal violations: {len(report.violations)}")
