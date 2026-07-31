from wm_agents_validator.models.plugin_result import PluginResult, Violation
from wm_agents_validator.models.verification import VerificationReport
from wm_agents_validator.report.console_reporter import print_console_report


def _report(**overrides) -> VerificationReport:
    defaults = dict(
        trace_id="trace-1",
        contract_id="contract@1.0.0",
        passed=True,
        overall_score=1.0,
        plugin_results=[],
    )
    defaults.update(overrides)
    return VerificationReport(**defaults)


def test_prints_check_lines_for_passing_plugin(capsys):
    report = _report(
        plugin_results=[
            PluginResult(
                plugin="input_context",
                passed=True,
                score=1.0,
                evidence={
                    "checks": {
                        "apiservice": {"passed": True, "detail": "context fully grounded"},
                        "widget": {"passed": True, "detail": "context fully grounded"},
                    }
                },
            )
        ],
    )

    print_console_report(report)
    out = capsys.readouterr().out

    # A clean pass must still show what was checked, not just the bare score.
    assert "apiservice: context fully grounded" in out
    assert "widget: context fully grounded" in out


def test_prints_check_lines_for_failing_plugin_without_duplicating_violation(capsys):
    report = _report(
        passed=False,
        overall_score=0.5,
        plugin_results=[
            PluginResult(
                plugin="input_context",
                passed=False,
                score=0.5,
                evidence={
                    "checks": {
                        "apiservice": {
                            "passed": False,
                            "detail": "expected file(s) never retrieved by any tool",
                        },
                        "widget": {"passed": True, "detail": "context fully grounded"},
                    }
                },
                violations=[
                    Violation(
                        code="context_path_not_retrieved",
                        message="apiservice never retrieved",
                        plugin="input_context",
                        resource="apiservice",
                    ),
                    Violation(
                        code="unrelated_context_fetched",
                        message="extra file read",
                        plugin="input_context",
                    ),
                ],
            )
        ],
    )

    print_console_report(report)
    out = capsys.readouterr().out

    assert "apiservice: expected file(s) never retrieved by any tool" in out
    assert "widget: context fully grounded" in out
    # The resource-scoped violation is already reflected in the check line
    # above and must not be printed a second time as a raw violation.
    assert "context_path_not_retrieved: apiservice never retrieved" not in out
    # A violation with no matching check label still prints normally.
    assert "unrelated_context_fetched: extra file read" in out


def test_prints_check_lines_for_resource_usage_budget_metrics(capsys):
    # resource_usage populates the same generic evidence["checks"] contract
    # for its budgeted metrics (duration/tokens/cost), so it gets the same
    # "show what passed too" treatment as input_context, for free.
    report = _report(
        passed=False,
        overall_score=0.5,
        plugin_results=[
            PluginResult(
                plugin="resource_usage",
                passed=False,
                score=0.5,
                evidence={
                    "checks": {
                        "Trace duration (ms)": {"passed": True, "detail": "1000 within budget of 60000"},
                        "Total tokens": {"passed": False, "detail": "25000 exceeded budget of 20000"},
                    }
                },
                violations=[
                    Violation(
                        code="token_budget_exceeded",
                        message="Total tokens of 25000 exceeded budget of 20000",
                        plugin="resource_usage",
                        resource="Total tokens",
                    ),
                ],
            )
        ],
    )

    print_console_report(report)
    out = capsys.readouterr().out

    assert "Trace duration (ms): 1000 within budget of 60000" in out
    assert "Total tokens: 25000 exceeded budget of 20000" in out
    assert "token_budget_exceeded: Total tokens of 25000 exceeded budget of 20000" not in out


def test_prints_plain_violations_for_plugins_without_checks_evidence(capsys):
    report = _report(
        passed=True,
        plugin_results=[
            PluginResult(
                plugin="skills_loaded",
                passed=True,
                score=0.9,
                violations=[
                    Violation(
                        code="extra_skill_loaded",
                        message="loaded an extra skill",
                        plugin="skills_loaded",
                    )
                ],
            )
        ],
    )

    print_console_report(report)
    out = capsys.readouterr().out

    assert "extra_skill_loaded: loaded an extra skill" in out
