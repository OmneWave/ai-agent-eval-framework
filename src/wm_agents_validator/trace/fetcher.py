from __future__ import annotations

import base64
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from langfuse import get_client

from wm_agents_validator.models.raw_trace import RawTracePayload

OBSERVATION_PAGE_SIZE = 100
MAX_OBSERVATION_PAGES = 10


def _to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return {k: _to_dict(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


def _auth_header() -> dict[str, str]:
    public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
    secret_key = os.environ["LANGFUSE_SECRET_KEY"]
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _extract_observations(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("data", "observations"):
        value = body.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _observations_from_trace(trace: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not trace:
        return []
    observations = trace.get("observations")
    if isinstance(observations, list):
        return [item for item in observations if isinstance(item, dict)]
    return []


def _merge_observation_pages(
    client: httpx.Client,
    headers: dict[str, str],
    url: str,
    base_params: dict[str, Any],
    *,
    use_cursor: bool,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    cursor: str | None = None
    page = int(base_params.get("page", 1))

    for _ in range(MAX_OBSERVATION_PAGES):
        params = dict(base_params)
        if use_cursor and cursor:
            params["cursor"] = cursor
        elif not use_cursor:
            params["page"] = page

        response = client.get(url, headers=headers, params=params)
        if response.status_code != 200:
            break

        body = response.json()
        batch = _extract_observations(body)
        observations.extend(batch)

        if use_cursor:
            meta = body.get("meta") if isinstance(body, dict) else None
            cursor = meta.get("cursor") if isinstance(meta, dict) else None
            if not cursor or not batch:
                break
            continue

        if len(batch) < int(params.get("limit", OBSERVATION_PAGE_SIZE)):
            break
        page += 1

    return observations


def _fetch_observations_rest(
    client: httpx.Client,
    base: str,
    headers: dict[str, str],
    trace_id: str,
    trace: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    embedded = _observations_from_trace(trace)
    if embedded:
        return embedded

    v2_url = f"{base}/api/public/v2/observations"
    v1_url = f"{base}/api/public/observations"
    time_window = {
        "fromStartTime": "2020-01-01T00:00:00.000Z",
        "toStartTime": "2030-12-31T23:59:59.999Z",
    }
    base_trace_filter = {"traceId": trace_id, "limit": OBSERVATION_PAGE_SIZE}

    strategies: list[tuple[str, dict[str, Any], bool]] = [
        (v2_url, {**base_trace_filter, "fields": "core,basic,io,usage"}, True),
        (v2_url, {**base_trace_filter, "fields": "core,basic"}, True),
        (v1_url, {**base_trace_filter, "page": 1}, False),
        (v1_url, {**base_trace_filter, "page": 1, **time_window}, False),
    ]

    for url, params, use_cursor in strategies:
        observations = _merge_observation_pages(
            client, headers, url, params, use_cursor=use_cursor
        )
        if observations:
            return observations

    trace_resp = client.get(
        f"{base}/api/public/traces/{trace_id}",
        headers=headers,
        params={"fields": "core,observations"},
    )
    if trace_resp.status_code == 200:
        return _observations_from_trace(trace_resp.json())

    return []


def _observations_from_sdk_result(data: Any) -> list[dict[str, Any]]:
    parsed = _to_dict(data)
    observations = _extract_observations(parsed)
    if observations:
        return observations
    if isinstance(parsed, dict):
        return _observations_from_trace(parsed)
    return []


def fetch_via_rest(trace_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
    headers = _auth_header()

    with httpx.Client(timeout=30.0) as client:
        trace_resp = client.get(f"{base}/api/public/traces/{trace_id}", headers=headers)
        trace_resp.raise_for_status()
        trace = trace_resp.json()
        observations = _fetch_observations_rest(client, base, headers, trace_id, trace)

    return trace, observations


def fetch_via_sdk(trace_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    langfuse = get_client()
    trace: dict[str, Any] | None = None
    observations: list[dict[str, Any]] = []

    for getter in (
        lambda: langfuse.api.legacy.trace.get(trace_id=trace_id),
        lambda: langfuse.api.trace.get(trace_id=trace_id),
        lambda: langfuse.api.trace.get(trace_id=trace_id, fields="core,observations"),
    ):
        try:
            trace = _to_dict(getter())
            observations = _observations_from_trace(trace)
            if trace is not None:
                break
        except AttributeError:
            continue
        except Exception:
            continue

    if observations:
        return trace, observations

    for getter in (
        lambda: langfuse.api.observations.get_many(
            trace_id=trace_id,
            limit=OBSERVATION_PAGE_SIZE,
            fields="core,basic,io,usage",
        ),
        lambda: langfuse.api.observations.get_many(
            trace_id=trace_id, limit=OBSERVATION_PAGE_SIZE
        ),
        lambda: langfuse.api.legacy.observations_v1.get_many(
            trace_id=trace_id, limit=OBSERVATION_PAGE_SIZE, page=1
        ),
    ):
        try:
            observations = _observations_from_sdk_result(getter())
            if observations:
                break
        except AttributeError:
            continue
        except Exception:
            continue

    return trace, observations


def fetch_trace(
    trace_id: str,
    retries: int = 12,
    delay_sec: float = 1.0,
) -> RawTracePayload:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            trace, observations = fetch_via_sdk(trace_id)
            if not observations:
                rest_trace, observations = fetch_via_rest(trace_id)
                trace = trace or rest_trace
            return RawTracePayload(
                trace_id=trace_id,
                trace=trace,
                observations=observations,
                fetched_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(delay_sec)

    raise RuntimeError(
        f"Could not fetch trace {trace_id} after {retries} attempts"
    ) from last_error
