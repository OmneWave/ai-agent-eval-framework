from wm_agents_validator.plugins.intent_verification import IntentVerificationPlugin
from wm_agents_validator.plugins.metadata_gate import MetadataGatePlugin
from wm_agents_validator.plugins.runner import run_plugins
from wm_agents_validator.plugins.tool_policy import ToolPolicyPlugin


def test_intent_verification_passes(snapshot, contract):
    result = IntentVerificationPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0


def test_intent_verification_fails_wrong_skill(snapshot, contract):
    snapshot.skill_loads[0].skill_names = ["wrong_skill"]
    result = IntentVerificationPlugin().evaluate(snapshot, contract)
    assert not result.passed
    assert result.score == 0.5


def test_metadata_gate_passes(snapshot, contract):
    result = MetadataGatePlugin().evaluate(snapshot, contract)
    assert result.passed


def test_tool_policy_passes(snapshot, contract, context):
    result = ToolPolicyPlugin().evaluate(snapshot, contract, context)
    assert result.passed


def test_full_runner_passes(snapshot, contract, context):
    report = run_plugins(snapshot, contract, context=context)
    assert report.overall_score > 0.5
    assert report.trace_id == "test-trace-001"
    assert len(report.plugin_results) == 7
