from __future__ import annotations

import ast
import json
from typing import Any

from wm_agents_validator.models.raw_trace import RawTracePayload
from wm_agents_validator.models.trace_snapshot import (
    DELEGATION_TOOL_NAMES,
    EventRecord,
    FailedToolRecord,
    GenerationRecord,
    SKILL_TOOL,
    SkillLoadRecord,
    SpanRecord,
    ToolsSummary,
    TraceSnapshot,
    _span_base_name,
)

MAX_OUTPUT_BYTES = 2048
# Keys that are large/internal and shouldn't be copied verbatim into
# TraceSnapshot.metadata (they're either handled specially below or add noise).
_BULKY_METADATA_KEYS = frozenset({"resourceAttributes"})


def _obs_get(obs: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obs and obs[key] is not None:
            return obs[key]
    return None


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _truncate_output(value: Any) -> Any:
    try:
        text = json.dumps(value, default=str)
    except TypeError:
        text = str(value)
    if len(text) <= MAX_OUTPUT_BYTES:
        return value
    return {"_truncated": True, "preview": text[:MAX_OUTPUT_BYTES]}


def _strip_thinking(text: str) -> str:
    lower = text.lower()
    closing = "</think>"
    if closing in lower:
        idx = lower.rfind(closing)
        return text[idx + len(closing) :].strip()
    return text.strip()


def _message_content(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if content is None:
        return None
    return str(content)


def _extract_prompts_from_trace(trace: dict[str, Any]) -> tuple[str | None, str | None]:
    user_prompt: str | None = None
    final_response: str | None = None

    trace_input = trace.get("input")
    if isinstance(trace_input, dict):
        for message in trace_input.get("messages") or []:
            if not isinstance(message, dict):
                continue
            if str(message.get("type") or "").lower() == "human":
                content = _message_content(message)
                if content:
                    user_prompt = content.strip()
                    if user_prompt.startswith("<wm-page"):
                        user_prompt = None
                    break

    trace_output = trace.get("output")
    if isinstance(trace_output, dict):
        for message in reversed(trace_output.get("messages") or []):
            if not isinstance(message, dict):
                continue
            if str(message.get("type") or "").lower() != "ai":
                continue
            if message.get("tool_calls"):
                continue
            content = _message_content(message)
            if content:
                final_response = _strip_thinking(content)
                break

    return user_prompt, final_response


def _extract_skill_names(tool_input: Any) -> list[str]:
    parsed = _parse_json(tool_input)
    if isinstance(parsed, dict):
        skills = parsed.get("skills") or parsed.get("skill") or []
        if isinstance(skills, str):
            return [skills]
        if isinstance(skills, list):
            return [str(skill) for skill in skills]
    if isinstance(parsed, list):
        return [str(skill) for skill in parsed]
    return []


def _extract_skill_loads_from_messages(
    messages: Any,
    *,
    default_timestamp: str | None = None,
    agent_id: str | None = None,
) -> list[SkillLoadRecord]:
    if not isinstance(messages, list):
        return []

    pending: dict[str, list[str]] = {}
    results: list[SkillLoadRecord] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        msg_type = str(message.get("type") or "")

        if msg_type == "ai":
            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict) or tool_call.get("name") != SKILL_TOOL:
                    continue
                skill_names = _extract_skill_names(tool_call.get("args"))
                tool_call_id = tool_call.get("id")
                if tool_call_id and skill_names:
                    pending[str(tool_call_id)] = skill_names
                elif skill_names:
                    results.append(
                        SkillLoadRecord(
                            skill_names=skill_names,
                            success=True,
                            timestamp=default_timestamp,
                            agent_id=agent_id,
                        )
                    )
            continue

        if msg_type != "tool" or message.get("name") != SKILL_TOOL:
            continue

        tool_call_id = message.get("tool_call_id")
        skill_names = pending.pop(str(tool_call_id), []) if tool_call_id else []
        status = str(message.get("status") or "success").lower()
        success = status not in ("error", "failed", "failure")
        results.append(
            SkillLoadRecord(
                skill_names=skill_names,
                success=success,
                timestamp=default_timestamp,
                agent_id=agent_id,
                error_message=None if success else str(message.get("content") or status),
            )
        )

    for skill_names in pending.values():
        results.append(
            SkillLoadRecord(
                skill_names=skill_names,
                success=True,
                timestamp=default_timestamp,
                agent_id=agent_id,
            )
        )

    return results


def _merge_skill_loads(
    existing: list[SkillLoadRecord], extra: list[SkillLoadRecord]
) -> list[SkillLoadRecord]:
    seen = {(tuple(load.skill_names), load.success) for load in existing}
    merged = list(existing)
    for load in extra:
        key = (tuple(load.skill_names), load.success)
        if key not in seen:
            merged.append(load)
            seen.add(key)
    return merged


def _extract_skill_loads_from_trace(
    trace: dict[str, Any], observations: list[dict[str, Any]], entry_agent: str | None
) -> list[SkillLoadRecord]:
    loads: list[SkillLoadRecord] = []

    for section in (trace.get("input"), trace.get("output")):
        if isinstance(section, dict):
            loads.extend(
                _extract_skill_loads_from_messages(
                    section.get("messages"), agent_id=entry_agent
                )
            )

    for obs in observations:
        if str(_obs_get(obs, "type", "observationType") or "").upper() != "GENERATION":
            continue
        parsed_input = _parse_json(_obs_get(obs, "input"))
        timestamp = _obs_get(obs, "startTime", "start_time")
        ts = str(timestamp) if timestamp else None
        meta = _parse_json(_obs_get(obs, "metadata")) or {}
        agent_id = None
        if isinstance(meta, dict):
            agent_id = meta.get("agentid") or meta.get("entryagentid")
        if isinstance(parsed_input, dict):
            loads.extend(
                _extract_skill_loads_from_messages(
                    parsed_input.get("messages"),
                    default_timestamp=ts,
                    agent_id=str(agent_id) if agent_id else entry_agent,
                )
            )

    return loads


def _parse_tool_input(obs: dict[str, Any]) -> dict[str, Any]:
    meta = _parse_json(_obs_get(obs, "metadata")) or {}
    if not isinstance(meta, dict):
        meta = {}

    parsed: dict[str, Any]
    if isinstance(meta.get("inputs"), dict):
        parsed = dict(meta["inputs"])
    elif isinstance(meta.get("input"), dict):
        parsed = dict(meta["input"])
    else:
        raw = _obs_get(obs, "input")
        parsed_val = _parse_json(raw)
        if isinstance(parsed_val, dict):
            parsed = parsed_val
        elif isinstance(raw, str) and raw.strip().startswith("{"):
            try:
                literal = ast.literal_eval(raw)
                parsed = literal if isinstance(literal, dict) else {}
            except (ValueError, SyntaxError):
                parsed = {}
        else:
            parsed = {}

    base_name = _span_base_name(str(_obs_get(obs, "name", "observationName") or ""))
    if base_name in DELEGATION_TOOL_NAMES and "agent" in parsed and "target_agent" not in parsed:
        parsed = dict(parsed)
        parsed["target_agent"] = parsed["agent"]

    return parsed


def _parse_tool_output(obs: dict[str, Any]) -> Any:
    output = _obs_get(obs, "output")
    base_name = _span_base_name(str(_obs_get(obs, "name", "observationName") or ""))

    if isinstance(output, dict):
        status = str(output.get("status") or "").lower()
        if status in ("error", "failed", "failure"):
            message = output.get("content") or output.get("statusMessage")
            return _truncate_output({"status": "error", "message": message})

        if base_name in DELEGATION_TOOL_NAMES:
            content = output.get("content")
            if isinstance(content, str):
                try:
                    return _truncate_output(json.loads(content))
                except json.JSONDecodeError:
                    return _truncate_output({"response": content})

            update = output.get("update")
            if isinstance(update, dict):
                for message in update.get("messages") or []:
                    if not isinstance(message, dict) or message.get("type") != "tool":
                        continue
                    content = message.get("content")
                    if isinstance(content, str):
                        try:
                            return _truncate_output(json.loads(content))
                        except json.JSONDecodeError:
                            return _truncate_output({"response": content})

        if "content" in output and len(output) <= 3:
            return _truncate_output(output.get("content"))

    return _truncate_output(output)


def _tool_success(obs: dict[str, Any]) -> tuple[bool | None, str | None]:
    level = str(_obs_get(obs, "level") or "").upper()
    status_message = _obs_get(obs, "statusMessage", "status_message")
    if level == "ERROR" or status_message:
        return False, str(status_message) if status_message else None

    output = _obs_get(obs, "output")
    if isinstance(output, dict):
        status = str(output.get("status") or "").lower()
        if status in ("error", "failed", "failure"):
            message = output.get("content") or output.get("statusMessage")
            return False, str(message) if message else None

    if level == "DEFAULT" or not level:
        return True, None
    return None, None


def _obs_agent_id(obs: dict[str, Any], entry_agent: str | None) -> str | None:
    meta = _parse_json(_obs_get(obs, "metadata")) or {}
    if isinstance(meta, dict):
        agent = meta.get("agentid") or meta.get("entryagentid")
        if agent:
            return str(agent)
    return entry_agent


def _sort_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(obs: dict[str, Any]) -> str:
        return str(_obs_get(obs, "startTime", "start_time") or "")

    return sorted(observations, key=sort_key)


def _map_obs_type(obs_type: str) -> str | None:
    """Map Langfuse observation types to snapshot span types (1:1 where supported)."""
    mapping = {
        "SPAN": "SPAN",
        "TOOL": "TOOL",
        "EVENT": "EVENT",
        "GENERATION": "GENERATION",
        "AGENT": "AGENT",
        "CHAIN": "CHAIN",
        "RETRIEVER": "RETRIEVER",
        "EVALUATOR": "EVALUATOR",
        "EMBEDDING": "EMBEDDING",
        "GUARDRAIL": "GUARDRAIL",
    }
    return mapping.get(obs_type.upper())


def _build_spans(
    observations: list[dict[str, Any]],
    *,
    trace: dict[str, Any],
    trace_id: str,
    entry_agent: str | None,
) -> list[SpanRecord]:
    spans: list[SpanRecord] = []
    trace_timestamp = _obs_get(trace, "timestamp", "startTime", "start_time")
    root_id = str(trace_id)
    spans.append(
        SpanRecord(
            id=root_id,
            name=entry_agent or str(_obs_get(trace, "name") or "agent"),
            type="AGENT_RUN",
            parent_id=None,
            agent_id=entry_agent,
            timestamp=str(trace_timestamp) if trace_timestamp else None,
            success=True,
        )
    )

    for obs in observations:
        obs_type_raw = str(_obs_get(obs, "type", "observationType") or "UNKNOWN").upper()
        mapped = _map_obs_type(obs_type_raw)
        if mapped is None:
            continue

        obs_id = str(_obs_get(obs, "id", "observationId") or "")
        if not obs_id:
            continue

        name = str(_obs_get(obs, "name", "observationName") or "")
        level = str(_obs_get(obs, "level") or "") or None
        timestamp = _obs_get(obs, "startTime", "start_time")
        end_time = _obs_get(obs, "endTime", "end_time")
        parent_id = _obs_get(obs, "parentObservationId", "parent_observation_id")

        span = SpanRecord(
            id=obs_id,
            name=name,
            type=mapped,  # type: ignore[arg-type]
            parent_id=str(parent_id) if parent_id else root_id,
            agent_id=_obs_agent_id(obs, entry_agent),
            timestamp=str(timestamp) if timestamp else None,
            end_time=str(end_time) if end_time else None,
            level=level,
        )

        if mapped == "TOOL":
            span.input = _parse_tool_input(obs)
            span.output = _parse_tool_output(obs)
            success, error_message = _tool_success(obs)
            span.success = success
            span.error_message = error_message
        elif mapped == "EVENT":
            event_input = _parse_json(_obs_get(obs, "input"))
            span.input = event_input if isinstance(event_input, dict) else {}
        elif mapped in ("AGENT", "CHAIN"):
            if not span.agent_id and name:
                span.agent_id = name
            if level and level.upper() == "ERROR":
                span.success = False
                status_message = _obs_get(obs, "statusMessage", "status_message")
                span.error_message = str(status_message) if status_message else None
            else:
                span.success = True
        elif level and level.upper() == "ERROR":
            span.success = False
            status_message = _obs_get(obs, "statusMessage", "status_message")
            span.error_message = str(status_message) if status_message else None

        spans.append(span)

    return spans


def _build_tools_summary(spans: list[SpanRecord]) -> ToolsSummary:
    called: list[str] = []
    failed: list[FailedToolRecord] = []
    seen_called: set[str] = set()

    for span in spans:
        if span.type != "TOOL":
            continue
        base_name = _span_base_name(span.name)
        if base_name not in seen_called:
            called.append(base_name)
            seen_called.add(base_name)
        if span.success is False:
            failed.append(
                FailedToolRecord(
                    name=base_name,
                    error_message=span.error_message,
                    timestamp=span.timestamp,
                    span_id=span.id,
                )
            )

    return ToolsSummary(called=called, failed=failed)


def _extract_skill_loads_from_spans(spans: list[SpanRecord]) -> list[SkillLoadRecord]:
    loads: list[SkillLoadRecord] = []
    for span in spans:
        if span.type != "TOOL":
            continue
        base_name = _span_base_name(span.name)
        if base_name != SKILL_TOOL:
            continue
        skill_names = _extract_skill_names(span.input)
        if not skill_names:
            continue
        loads.append(
            SkillLoadRecord(
                skill_names=skill_names,
                success=span.success is not False,
                timestamp=span.timestamp,
                agent_id=span.agent_id,
                error_message=span.error_message,
            )
        )
    return loads


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_usage_tokens(obs: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    """Handles both Langfuse's newer ``usageDetails`` and older ``usage`` shapes,
    plus the OpenAI-style prompt/completion naming some SDKs emit instead."""
    usage = _parse_json(_obs_get(obs, "usageDetails", "usage"))
    if not isinstance(usage, dict):
        usage = {}

    input_tokens = usage.get("input", usage.get("promptTokens", usage.get("input_tokens")))
    output_tokens = usage.get("output", usage.get("completionTokens", usage.get("output_tokens")))
    total_tokens = usage.get("total", usage.get("totalTokens", usage.get("total_tokens")))

    input_tokens = _as_int(input_tokens)
    output_tokens = _as_int(output_tokens)
    total_tokens = _as_int(total_tokens)
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)

    return input_tokens, output_tokens, total_tokens


def _extract_cost_usd(obs: dict[str, Any]) -> float | None:
    cost_details = _parse_json(_obs_get(obs, "costDetails"))
    if isinstance(cost_details, dict) and cost_details.get("total") is not None:
        try:
            return float(cost_details["total"])
        except (TypeError, ValueError):
            pass

    for key in ("calculatedTotalCost", "totalCost", "total_cost"):
        value = _obs_get(obs, key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue

    return None


def _build_generations(
    observations: list[dict[str, Any]], entry_agent: str | None
) -> list[GenerationRecord]:
    generations: list[GenerationRecord] = []
    for obs in observations:
        if str(_obs_get(obs, "type", "observationType") or "").upper() != "GENERATION":
            continue

        input_tokens, output_tokens, total_tokens = _extract_usage_tokens(obs)
        cost_usd = _extract_cost_usd(obs)
        if input_tokens is None and output_tokens is None and total_tokens is None and cost_usd is None:
            # No usage/cost data was fetched or attached to this generation; skip
            # rather than recording an all-None entry that would just be noise.
            continue

        timestamp = _obs_get(obs, "startTime", "start_time")
        generations.append(
            GenerationRecord(
                name=str(_obs_get(obs, "name", "observationName") or "") or None,
                agent_id=_obs_agent_id(obs, entry_agent),
                timestamp=str(timestamp) if timestamp else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
            )
        )
    return generations


def _build_custom_events(observations: list[dict[str, Any]]) -> list[EventRecord]:
    events: list[EventRecord] = []
    for obs in observations:
        obs_type = str(_obs_get(obs, "type", "observationType") or "").upper()
        if obs_type != "EVENT":
            continue
        name = str(_obs_get(obs, "name", "observationName") or "")
        timestamp = _obs_get(obs, "startTime", "start_time")
        event_input = _parse_json(_obs_get(obs, "input"))
        metadata = event_input if isinstance(event_input, dict) else {}
        events.append(
            EventRecord(
                name=name,
                metadata=metadata,
                timestamp=str(timestamp) if timestamp else None,
            )
        )
    return events


def _curate_metadata(trace: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    # Pass through all caller-supplied metadata (minus known-bulky keys) rather
    # than a hardcoded whitelist, so callers can stash arbitrary identifiers
    # (e.g. a custom user-id key) without normalizer.py needing to know about
    # every business-specific key name in advance.
    curated: dict[str, Any] = {
        key: value
        for key, value in metadata.items()
        if key not in _BULKY_METADATA_KEYS and value is not None
    }

    if "user_id" not in curated:
        native_user_id = trace.get("userId") if isinstance(trace, dict) else None
        if native_user_id:
            curated["user_id"] = native_user_id

    if "environment" not in curated:
        resource_attrs = metadata.get("resourceAttributes")
        if isinstance(resource_attrs, dict):
            env = resource_attrs.get("langfuse.environment")
            if env:
                curated["environment"] = env

    if "model_name" not in curated:
        trace_output = trace.get("output")
        if isinstance(trace_output, dict):
            for message in reversed(trace_output.get("messages") or []):
                if not isinstance(message, dict):
                    continue
                response_meta = message.get("response_metadata") or {}
                if isinstance(response_meta, dict) and response_meta.get("model_name"):
                    curated["model_name"] = response_meta["model_name"]
                    break

    if "contract_id" not in curated:
        curated["contract_id"] = metadata.get("contract_id")

    return curated


def _derive_status(trace: dict[str, Any], tools_summary: ToolsSummary) -> str:
    if tools_summary.failed:
        return "error"
    level = str(_obs_get(trace, "level") or "").lower()
    if level == "error":
        return "error"
    return "success" if trace else "unknown"


def _duration_from_timestamps(start: Any, end: Any) -> int | None:
    try:
        from datetime import datetime

        start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return int((end_dt - start_dt).total_seconds() * 1000)
    except (ValueError, TypeError):
        return None


def _compute_duration_ms(
    trace: dict[str, Any], observations: list[dict[str, Any]] | None = None
) -> int | None:
    # Langfuse's trace object doesn't expose an "endTime" of its own (only
    # observations do) — it reports duration as a pre-aggregated "latency" in
    # seconds instead. Prefer that; it's what the API actually returns.
    latency_seconds = _obs_get(trace, "latency")
    if latency_seconds is not None:
        try:
            latency = float(latency_seconds)
            if latency >= 0:
                return int(latency * 1000)
        except (TypeError, ValueError):
            pass

    start = _obs_get(trace, "timestamp", "startTime", "start_time")
    end = _obs_get(trace, "endTime", "end_time")
    if start and end:
        computed = _duration_from_timestamps(start, end)
        if computed is not None:
            return computed

    # Last resort: derive the span from whatever start/end timestamps the
    # fetched observations actually carry (ISO-8601 strings sort chronologically).
    timestamps = [str(start)] if start else []
    for obs in observations or []:
        for key in ("startTime", "start_time", "endTime", "end_time"):
            value = _obs_get(obs, key)
            if value:
                timestamps.append(str(value))
    if len(timestamps) >= 2:
        return _duration_from_timestamps(min(timestamps), max(timestamps))

    return None



def _extract_trace_total_cost(trace: dict[str, Any]) -> float | None:
    # When a fetch strategy requests fields excluding the "metrics" group
    # (e.g. fields="core,observations"), Langfuse returns -1 for totalCost/
    # latency instead of omitting them -- treat that sentinel as "unavailable".
    value = _obs_get(trace, "totalCost")
    if value is None:
        return None
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    return cost if cost >= 0 else None


def normalize_trace(payload: RawTracePayload) -> TraceSnapshot:
    trace = payload.trace or {}
    observations = _sort_observations(payload.observations)
    metadata = _parse_json(_obs_get(trace, "metadata")) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    entry_agent = metadata.get("entryagentid") or metadata.get("entry_agent_id")
    entry_agent_str = str(entry_agent) if entry_agent else None

    spans = _build_spans(
        observations,
        trace=trace,
        trace_id=payload.trace_id,
        entry_agent=entry_agent_str,
    )
    tools_summary = _build_tools_summary(spans)
    custom_events = _build_custom_events(observations)

    skill_loads = _merge_skill_loads(
        _extract_skill_loads_from_spans(spans),
        _extract_skill_loads_from_trace(trace, observations, entry_agent_str),
    )

    generations = _build_generations(observations, entry_agent_str)
    trace_total_cost_usd = _extract_trace_total_cost(trace)

    user_prompt, final_response = _extract_prompts_from_trace(trace)
    session_id = metadata.get("langfuse_session_id") or metadata.get("thread_id") or _obs_get(
        trace, "sessionId", "session_id"
    )
    run_id = metadata.get("run_id") or metadata.get("runId")

    return TraceSnapshot(
        trace_id=payload.trace_id,
        session_id=str(session_id) if session_id else None,
        run_id=str(run_id) if run_id else None,
        entry_agent=entry_agent_str,
        status=_derive_status(trace, tools_summary),  # type: ignore[arg-type]
        duration_ms=_compute_duration_ms(trace, observations),
        user_prompt=user_prompt,
        final_response=final_response,
        metadata=_curate_metadata(trace, metadata),
        custom_events=custom_events,
        skill_loads=skill_loads,
        tools_summary=tools_summary,
        spans=spans,
        generations=generations,
        trace_total_cost_usd=trace_total_cost_usd,
    )
