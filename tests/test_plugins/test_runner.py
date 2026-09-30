import pytest

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract
from wm_agents_validator.plugins import registry, runner


def _contract() -> WorkflowContract:
    return WorkflowContract.model_validate({"workflow": "w", "contract_version": "1.0.0", "skills": {"required": []}})


def _snapshot() -> TraceSnapshot:
    return TraceSnapshot(trace_id="t1", entry_agent="a", status="success", skill_loads=[])


def test_plugin_weights_sum_to_one():
    assert registry.PLUGIN_WEIGHTS == {
        "output": 0.4,
        "skills_loaded": 0.25,
        "tool_calls": 0.2,
        "input_context": 0.15,
    }
    assert sum(registry.PLUGIN_WEIGHTS.values()) == pytest.approx(1.0)


def test_run_plugins_weights_overall_score_by_plugin(monkeypatch):
    # Fixed per-plugin scores chosen so each weight's contribution is
    # individually distinguishable in the result -- proves the new
    # output-leaning weights (0.4/0.25/0.2/0.15) are actually applied, not
    # just present in the registry.
    fixed_scores = {
        "output": 0.5,
        "skills_loaded": 1.0,
        "tool_calls": 1.0,
        "input_context": 1.0,
        "trace_health": 0.0,  # zero-weight plugin -- must not move overall_score
        "resource_usage": 0.0,  # zero-weight plugin -- must not move overall_score
    }

    class _FakePlugin:
        def __init__(self, name: str):
            self._name = name

        def evaluate(self, snapshot, contract, context=None) -> PluginResult:
            return PluginResult(plugin=self._name, passed=True, score=fixed_scores[self._name], violations=[])

    monkeypatch.setattr(runner, "get_plugin", lambda name: _FakePlugin(name))

    report = runner.run_plugins(_snapshot(), _contract(), context=EvalContext())

    expected = (
        0.5 * 0.4  # output
        + 1.0 * 0.25  # skills_loaded
        + 1.0 * 0.2  # tool_calls
        + 1.0 * 0.15  # input_context
    )
    assert report.overall_score == pytest.approx(round(expected, 4))
    assert report.overall_score == pytest.approx(0.8)


def test_run_plugins_output_score_dominates_weighted_average(monkeypatch):
    # A low output score should pull overall_score down further than an
    # equally low score on any other plugin, since output now carries the
    # largest weight (0.4, vs 0.25/0.2/0.15 for the rest).
    def _make(low_plugin: str):
        scores = {
            "output": 1.0,
            "skills_loaded": 1.0,
            "tool_calls": 1.0,
            "input_context": 1.0,
            "trace_health": 0.0,
            "resource_usage": 0.0,
        }
        scores[low_plugin] = 0.0

        class _FakePlugin:
            def __init__(self, name: str):
                self._name = name

            def evaluate(self, snapshot, contract, context=None) -> PluginResult:
                return PluginResult(plugin=self._name, passed=True, score=scores[self._name], violations=[])

        return lambda name: _FakePlugin(name)

    monkeypatch.setattr(runner, "get_plugin", _make("output"))
    output_zero = runner.run_plugins(_snapshot(), _contract(), context=EvalContext())

    monkeypatch.setattr(runner, "get_plugin", _make("input_context"))
    input_context_zero = runner.run_plugins(_snapshot(), _contract(), context=EvalContext())

    assert output_zero.overall_score < input_context_zero.overall_score
