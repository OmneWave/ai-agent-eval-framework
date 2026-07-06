import pytest

from wm_agents_validator.plugins.intent_verification import IntentVerificationPlugin
from wm_agents_validator.plugins.runner import run_plugins
from wm_agents_validator.plugins.tool_policy import ToolPolicyPlugin


def test_intent_verification_passes(snapshot, contract):
    result = IntentVerificationPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0


def test_intent_verification_fails_wrong_skill(snapshot, contract):
    expected_count = len(contract.intent.expected_skill)
    snapshot.skill_loads[0].skill_names = ["wrong_skill"]
    result = IntentVerificationPlugin().evaluate(snapshot, contract)
    assert not result.passed
    # 1 expected skill missing + 1 unexpected skill loaded: correct / (expected + extra)
    assert result.score == pytest.approx((expected_count - 1) / (expected_count + 1))
    codes = [v.code for v in result.violations]
    assert "skill_not_loaded" in codes
    assert "extra_skill_loaded" in codes
    assert "wrong_skill" in result.evidence["extra_skills_loaded"]


def test_intent_verification_fails_all_skills_missing(snapshot, contract):
    snapshot.skill_loads = []
    result = IntentVerificationPlugin().evaluate(snapshot, contract)
    assert not result.passed
    assert result.score == 0.0
    assert result.violations[0].code == "skill_not_loaded"


def test_intent_verification_flags_extra_skill_and_lowers_score(snapshot, contract):
    expected_count = len(contract.intent.expected_skill)
    snapshot.skill_loads.append(
        snapshot.skill_loads[0].model_copy(update={"skill_names": ["extra-unexpected-skill"]})
    )
    result = IntentVerificationPlugin().evaluate(snapshot, contract)
    assert result.passed  # all required skills still loaded, so it's not a hard failure
    assert result.score == pytest.approx(expected_count / (expected_count + 1))
    assert result.score < 1.0
    assert "extra-unexpected-skill" in result.evidence["extra_skills_loaded"]
    codes = [v.code for v in result.violations]
    assert codes == ["extra_skill_loaded"]


def test_intent_verification_treats_loaded_allowed_skill_as_optional(snapshot, contract):
    # Fixture already loads both allowed_skills ("explore-codebase", "explore-api");
    # since they're optional, loading them must not count as "extra" or lower the score.
    result = IntentVerificationPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert set(result.evidence["optional_skills_loaded"]) == {"explore-codebase", "explore-api"}
    assert result.evidence["extra_skills_loaded"] == []
    assert result.violations == []


def test_intent_verification_does_not_require_allowed_skill(snapshot, contract):
    # Dropping an allowed (optional) skill load must not be treated as "missing".
    snapshot.skill_loads = [
        load for load in snapshot.skill_loads if load.skill_names != ["explore-codebase"]
    ]
    result = IntentVerificationPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []


def test_tool_policy_passes(snapshot, contract, context):
    result = ToolPolicyPlugin().evaluate(snapshot, contract, context)
    assert result.passed


def test_full_runner_passes(snapshot, contract, context):
    report = run_plugins(snapshot, contract, context=context)
    assert report.overall_score > 0.5
    assert report.trace_id == "test-trace-001"
    assert len(report.plugin_results) == 8
