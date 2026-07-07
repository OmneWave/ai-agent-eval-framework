from wm_agents_validator.plugins.resource_coverage import ResourceCoveragePlugin


def test_resource_coverage_passes_with_fixture(snapshot, contract):
    result = ResourceCoveragePlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    # Standard evidence["checks"] contract: one entry per resource, pass or
    # fail, so a clean pass still shows what was actually checked.
    assert set(result.evidence["checks"]) == {"apiservice", "variable", "widget", "planning order"}
    assert all(c["passed"] for c in result.evidence["checks"].values())


def test_resource_coverage_flags_missing_agent(snapshot, contract):
    # Drop every span that puts wm_backend_expert in the trace, whether via
    # its own agent_id or as a delegation target.
    snapshot.spans = [
        s
        for s in snapshot.spans
        if s.agent_id != "wm_backend_expert" and s.id not in {"span-deleg-backend"}
    ]

    result = ResourceCoveragePlugin().evaluate(snapshot, contract)

    assert not result.passed
    assert result.score < 1.0
    codes = [v.code for v in result.violations]
    assert "agent_not_present" in codes

    checks = result.evidence["checks"]
    assert checks["apiservice"]["passed"] is False
    assert "wm_backend_expert" in checks["apiservice"]["detail"]
    assert checks["variable"]["passed"] is True

    missing_violation = next(v for v in result.violations if v.code == "agent_not_present")
    assert missing_violation.resource == "apiservice"


def test_resource_coverage_flags_planning_order_violation(snapshot, contract):
    # The fixture delegates to wm_backend_expert (apiservice) before
    # wm_ui_expert (variable/widget), matching the contract's resource
    # declaration order. Swap the delegation targets so wm_ui_expert is
    # delegated to first -> agents appear out of the expected order.
    for span in snapshot.spans:
        if span.id == "span-deleg-backend":
            span.input = {**span.input, "target_agent": "wm_ui_expert"}
        elif span.id == "span-deleg-ui":
            span.input = {**span.input, "target_agent": "wm_backend_expert"}

    result = ResourceCoveragePlugin().evaluate(snapshot, contract)

    assert result.evidence["planning_order_satisfied"] is False
    checks = result.evidence["checks"]
    assert checks["planning order"]["passed"] is False
    codes = [v.code for v in result.violations]
    assert "planning_order_violated" in codes
    order_violation = next(v for v in result.violations if v.code == "planning_order_violated")
    assert order_violation.resource == "planning order"
