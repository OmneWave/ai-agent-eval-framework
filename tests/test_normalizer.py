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
    assert contract.skills.required[0].name == "ui_to_api_binding_workflow"
    assert contract.resources.api[0].name == "petstore"


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


def test_normalizer_computes_duration_from_trace_latency():
    # Real Langfuse trace objects (GET /api/public/traces/{id}) expose a
    # pre-aggregated "latency" in seconds and have no trace-level "endTime"
    # at all -- only observations do. This is the primary source of duration.
    payload_obs = {
        "trace_id": "t1",
        "trace": {
            "metadata": {"entryagentid": "wm_agent"},
            "name": "wm_agent",
            "timestamp": "2026-01-01T10:00:00Z",
            "latency": 45.5,
        },
        "observations": [],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert snap.duration_ms == 45500


def test_normalizer_computes_duration_from_trace_start_end_when_no_latency():
    payload_obs = {
        "trace_id": "t1",
        "trace": {
            "metadata": {"entryagentid": "wm_agent"},
            "name": "wm_agent",
            "timestamp": "2026-01-01T10:00:00Z",
            "endTime": "2026-01-01T10:00:30Z",
        },
        "observations": [],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert snap.duration_ms == 30000


def test_normalizer_derives_duration_from_observation_timestamps_as_last_resort():
    # No "latency" and no trace-level "endTime" (the real-world case) -- fall
    # back to the span of observation start/end timestamps we did fetch.
    payload_obs = {
        "trace_id": "t1",
        "trace": {
            "metadata": {"entryagentid": "wm_agent"},
            "name": "wm_agent",
            "timestamp": "2026-01-01T10:00:00Z",
        },
        "observations": [
            {
                "id": "tool-1",
                "type": "TOOL",
                "name": "read_files",
                "startTime": "2026-01-01T10:00:01Z",
                "endTime": "2026-01-01T10:00:02Z",
            },
            {
                "id": "tool-2",
                "type": "TOOL",
                "name": "write_file",
                "startTime": "2026-01-01T10:00:10Z",
                "endTime": "2026-01-01T10:00:20Z",
            },
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert snap.duration_ms == 20000  # trace timestamp (10:00:00) to last obs endTime (10:00:20)


def test_normalizer_ignores_negative_one_sentinel_for_latency_and_total_cost():
    # Langfuse returns -1 for latency/totalCost when the "metrics" field group
    # was excluded from the fetch (e.g. fields="core,observations"), rather
    # than omitting the fields -- this must not be treated as a real value.
    payload_obs = {
        "trace_id": "t1",
        "trace": {
            "metadata": {"entryagentid": "wm_agent"},
            "name": "wm_agent",
            "timestamp": "2026-01-01T10:00:00Z",
            "latency": -1,
            "totalCost": -1,
        },
        "observations": [],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert snap.duration_ms is None
    assert snap.total_cost_usd is None


def test_normalizer_falls_back_to_trace_total_cost_when_no_generation_usage():
    payload_obs = {
        "trace_id": "t1",
        "trace": {
            "metadata": {"entryagentid": "wm_agent"},
            "name": "wm_agent",
            "totalCost": 0.042,
        },
        "observations": [],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert snap.generations == []
    assert snap.total_cost_usd == 0.042


def test_normalizer_prefers_generation_cost_sum_over_trace_total_cost():
    payload_obs = {
        "trace_id": "t1",
        "trace": {
            "metadata": {"entryagentid": "wm_agent"},
            "name": "wm_agent",
            "totalCost": 999.0,
        },
        "observations": [
            {
                "id": "gen-1",
                "type": "GENERATION",
                "name": "ChatOpenAI",
                "startTime": "2026-01-01T10:00:01Z",
                "usageDetails": {"total": 1000},
                "costDetails": {"total": 0.01},
            },
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert snap.total_cost_usd == 0.01


def test_normalizer_extracts_usage_and_cost_from_generation_usage_details():
    payload_obs = {
        "trace_id": "t1",
        "trace": {"metadata": {"entryagentid": "wm_agent"}, "name": "wm_agent"},
        "observations": [
            {
                "id": "gen-1",
                "type": "GENERATION",
                "name": "ChatOpenAI",
                "metadata": {"agentid": "wm_ui_expert"},
                "startTime": "2026-01-01T10:00:07Z",
                "usageDetails": {"input": 1200, "output": 300, "total": 1500},
                "costDetails": {"input": 0.01, "output": 0.02, "total": 0.03},
            },
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert len(snap.generations) == 1
    gen = snap.generations[0]
    assert gen.agent_id == "wm_ui_expert"
    assert gen.input_tokens == 1200
    assert gen.output_tokens == 300
    assert gen.total_tokens == 1500
    assert gen.cost_usd == 0.03
    assert snap.total_tokens == 1500
    assert snap.total_cost_usd == 0.03


def test_normalizer_extracts_usage_from_legacy_usage_and_flat_cost_fields():
    # Older Langfuse shapes: "usage" (not "usageDetails") with OpenAI-style
    # prompt/completion naming, and a flat calculatedTotalCost instead of costDetails.
    payload_obs = {
        "trace_id": "t1",
        "trace": {"metadata": {"entryagentid": "wm_agent"}, "name": "wm_agent"},
        "observations": [
            {
                "id": "gen-1",
                "type": "GENERATION",
                "name": "ChatOpenAI",
                "startTime": "2026-01-01T10:00:07Z",
                "usage": {"promptTokens": 800, "completionTokens": 200},
                "calculatedTotalCost": 0.015,
            },
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert len(snap.generations) == 1
    gen = snap.generations[0]
    assert gen.input_tokens == 800
    assert gen.output_tokens == 200
    assert gen.total_tokens == 1000  # derived from input+output when "total" absent
    assert gen.cost_usd == 0.015


def test_normalizer_sums_usage_across_multiple_generations():
    payload_obs = {
        "trace_id": "t1",
        "trace": {"metadata": {"entryagentid": "wm_agent"}, "name": "wm_agent"},
        "observations": [
            {
                "id": "gen-1",
                "type": "GENERATION",
                "name": "ChatOpenAI",
                "startTime": "2026-01-01T10:00:01Z",
                "usageDetails": {"total": 1000},
                "costDetails": {"total": 0.01},
            },
            {
                "id": "gen-2",
                "type": "GENERATION",
                "name": "ChatOpenAI",
                "startTime": "2026-01-01T10:00:02Z",
                "usageDetails": {"total": 500},
                "costDetails": {"total": 0.005},
            },
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert snap.total_tokens == 1500
    assert snap.total_cost_usd == pytest.approx(0.015)


def test_normalizer_skips_generations_with_no_usage_or_cost_data():
    payload_obs = {
        "trace_id": "t1",
        "trace": {"metadata": {"entryagentid": "wm_agent"}, "name": "wm_agent"},
        "observations": [
            {
                "id": "gen-1",
                "type": "GENERATION",
                "name": "ChatOpenAI",
                "startTime": "2026-01-01T10:00:01Z",
            },
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))
    assert snap.generations == []
    assert snap.total_tokens is None
    assert snap.total_cost_usd is None


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


def test_normalizer_surfaces_wrapped_tool_name_from_execute_tool():
    payload_obs = {
        "trace_id": "t1",
        "trace": {"metadata": {"entryagentid": "wm_agent"}, "name": "wm_agent"},
        "observations": [
            {
                "id": "tool-execute",
                "type": "TOOL",
                "name": "execute_tool",
                "metadata": {
                    "inputs": {
                        "tool_name": "ui_createApiAwareVariable",
                        "tool_args": {"variableName": "list1"},
                    }
                },
                "startTime": "2026-01-01T10:00:00Z",
            }
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))

    assert "execute_tool" in snap.tools_summary.called
    assert "ui_createApiAwareVariable" in snap.tools_summary.called
    assert "ui_createApiAwareVariable" in snap.tool_names


def test_normalizer_records_failed_execute_tool_under_wrapped_tool_name():
    payload_obs = {
        "trace_id": "t1",
        "trace": {"metadata": {"entryagentid": "wm_agent"}, "name": "wm_agent"},
        "observations": [
            {
                "id": "tool-execute",
                "type": "TOOL",
                "name": "execute_tool",
                "level": "ERROR",
                "statusMessage": "boom",
                "metadata": {
                    "inputs": {
                        "tool_name": "ui_createApiAwareVariable",
                        "tool_args": {},
                    }
                },
                "startTime": "2026-01-01T10:00:00Z",
            }
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))

    failed_names = {failure.name for failure in snap.tools_summary.failed}
    assert failed_names == {"ui_createApiAwareVariable"}


def test_normalizer_does_not_unwrap_non_execute_tool_spans():
    payload_obs = {
        "trace_id": "t1",
        "trace": {"metadata": {"entryagentid": "wm_agent"}, "name": "wm_agent"},
        "observations": [
            {
                "id": "tool-write",
                "type": "TOOL",
                "name": "write_file",
                "metadata": {"inputs": {"tool_name": "should_not_be_extracted"}},
                "startTime": "2026-01-01T10:00:00Z",
            }
        ],
    }

    snap = normalize_trace(RawTracePayload.model_validate(payload_obs))

    assert snap.tools_summary.called == ["write_file"]


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
