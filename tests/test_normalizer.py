import json
from pathlib import Path

import pytest

from wm_agents_validator.models.raw_trace import RawTracePayload
from wm_agents_validator.trace.normalizer import normalize_trace

FIXTURES = Path(__file__).parent / "fixtures"
CONTRACTS = Path(__file__).parent.parent / "contracts"
REGRESSION_RAW = FIXTURES / "c4739a_regression_raw.json"
FULL_RAW_TRACE = Path(__file__).parent.parent / "trace-artifacts" / "c4739a2868e2b7aca6430aeae2f7ea0a_raw.json"


def test_load_contract(contract):
    assert contract.workflow == "ui_to_api_binding"
    assert contract.intent.expected_skill == "ui_to_api_binding_workflow"
    assert "apiservice" in contract.resources


def test_normalizer_includes_agent_and_chain_spans():
    payload_obs = {
        "trace_id": "t1",
        "trace": {"metadata": {"entryagentid": "wm_agent"}, "name": "wm_agent"},
        "observations": [
            {
                "id": "agent-wm",
                "type": "AGENT",
                "name": "wm_agent",
                "metadata": {"agentid": "wm_agent"},
                "startTime": "2026-01-01T10:00:00Z",
            },
            {
                "id": "tool-deleg",
                "type": "TOOL",
                "name": "start_new_conversation_with_agent",
                "parentObservationId": "agent-wm",
                "metadata": {"inputs": {"agent": "wm_ui_expert", "task": "bind UI"}},
                "startTime": "2026-01-01T10:00:05Z",
            },
            {
                "id": "chain-ui",
                "type": "CHAIN",
                "name": "wm_ui_expert",
                "parentObservationId": "tool-deleg",
                "metadata": {"agentid": "wm_ui_expert"},
                "startTime": "2026-01-01T10:00:06Z",
            },
            {
                "id": "gen-1",
                "type": "GENERATION",
                "name": "ChatOpenAI",
                "parentObservationId": "chain-ui",
                "metadata": {"agentid": "wm_ui_expert"},
                "startTime": "2026-01-01T10:00:07Z",
            },
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    span_ids = {span.id for span in snap.spans}
    assert "agent-wm" in span_ids
    assert "chain-ui" in span_ids

    chain_span = next(span for span in snap.spans if span.id == "chain-ui")
    assert chain_span.type == "CHAIN"
    assert chain_span.agent_id == "wm_ui_expert"
    assert chain_span.parent_id == "tool-deleg"

    gen_span = next(span for span in snap.spans if span.id == "gen-1")
    assert gen_span.parent_id == "chain-ui"


def test_normalizer_parses_load_skill():
    payload_obs = {
        "trace_id": "t1",
        "trace": {"metadata": {"entryagentid": "wm_agent"}, "name": "wm_agent"},
        "observations": [
            {
                "id": "tool-load-skill",
                "type": "TOOL",
                "name": "load_skill",
                "metadata": {"inputs": {"skills": ["ui_to_api_binding_workflow"]}},
                "startTime": "2026-01-01T10:00:00Z",
            },
            {
                "id": "tool-deleg",
                "type": "TOOL",
                "name": "start_new_conversation_with_agent",
                "metadata": {"inputs": {"agent": "wm_ui_expert", "task": "bind UI"}},
                "startTime": "2026-01-01T10:00:05Z",
            },
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert len(snap.skill_loads) == 1
    assert snap.skill_loads[0].skill_names == ["ui_to_api_binding_workflow"]
    assert len(snap.delegations) == 1
    assert snap.delegations[0].child_agent == "wm_ui_expert"
    deleg_span = next(s for s in snap.spans if s.name == "start_new_conversation_with_agent")
    assert deleg_span.input is not None
    assert deleg_span.input.get("target_agent") == "wm_ui_expert"


def test_normalizer_parses_load_skill_from_langgraph_messages():
    payload_obs = {
        "trace_id": "t1",
        "trace": {
            "metadata": {"entryagentid": "wm_agent"},
            "name": "wm_agent",
            "output": {
                "messages": [
                    {
                        "type": "ai",
                        "name": "wm_agent",
                        "tool_calls": [
                            {
                                "name": "load_skill",
                                "args": {"skills": ["ui_to_api_binding_workflow"]},
                                "id": "chatcmpl-tool-1",
                                "type": "tool_call",
                            }
                        ],
                    },
                    {
                        "type": "tool",
                        "name": "load_skill",
                        "tool_call_id": "chatcmpl-tool-1",
                        "status": "success",
                    },
                ]
            },
        },
        "observations": [],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert len(snap.skill_loads) == 1
    assert snap.skill_loads[0].skill_names == ["ui_to_api_binding_workflow"]
    assert snap.skill_loads[0].success is True


def test_normalizer_extracts_prompts_from_trace_messages():
    payload_obs = {
        "trace_id": "t1",
        "trace": {
            "metadata": {"entryagentid": "wm_agent"},
            "name": "wm_agent",
            "input": {
                "messages": [
                    {"type": "human", "content": "Bind list1 in Cards_1 to weavr_managedCardsGet"}
                ]
            },
            "output": {
                "messages": [
                    {
                        "type": "ai",
                        "content": "thinking...</think>\n\nTask 3 complete.",
                        "tool_calls": [],
                    }
                ]
            },
        },
        "observations": [],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert snap.user_prompt == "Bind list1 in Cards_1 to weavr_managedCardsGet"
    assert snap.final_response == "Task 3 complete."


@pytest.mark.parametrize(
    "raw_path",
    [REGRESSION_RAW, FULL_RAW_TRACE],
    ids=["fixture", "artifact"],
)
def test_normalizer_regression_c4739a_raw_trace(raw_path: Path):
    if not raw_path.exists():
        pytest.skip(f"raw trace not present: {raw_path}")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    snap = normalize_trace(RawTracePayload.model_validate(raw))

    assert "Bind list1 in Cards_1" in (snap.user_prompt or "")
    assert "weavr_managedCardsGet" in (snap.user_prompt or "")
    assert snap.final_response is not None
    assert "Binding Summary" in snap.final_response or "Task 3 complete" in snap.final_response

    failed_names = {failure.name for failure in snap.tools_summary.failed}
    assert "edit_file_content" in failed_names

    deleg_span = next(
        (
            span
            for span in snap.spans
            if span.type == "TOOL"
            and span.name.startswith("start_new_conversation_with_agent")
        ),
        None,
    )
    assert deleg_span is not None
    assert deleg_span.input is not None
    assert deleg_span.input.get("target_agent") == "wm_ui_expert"

    loaded_skills = [skill for load in snap.skill_loads for skill in load.skill_names]
    assert "ui_to_api_binding_workflow" in loaded_skills

    obs_types = {obs.get("type") for obs in raw.get("observations", [])}
    span_ids = {span.id for span in snap.spans}
    if "CHAIN" in obs_types:
        assert "9ad89473d5922125" in span_ids
        chain_span = next(span for span in snap.spans if span.id == "9ad89473d5922125")
        assert chain_span.type == "CHAIN"
        assert chain_span.name == "wm_ui_expert"
        assert chain_span.parent_id == "7d93767359195f5e"
    if "AGENT" in obs_types:
        assert "2ed469030c16eda9" in span_ids
        agent_span = next(span for span in snap.spans if span.id == "2ed469030c16eda9")
        assert agent_span.type == "AGENT"
        assert agent_span.name == "wm_agent"

    assert snap.tools_summary.called
    if any(
        obs.get("type") == "TOOL" and obs.get("name") == "load_skill"
        for obs in raw.get("observations", [])
    ):
        assert "load_skill" in snap.tools_summary.called
