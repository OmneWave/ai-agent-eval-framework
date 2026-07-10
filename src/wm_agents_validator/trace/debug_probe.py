from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from wm_agents_validator.trace.fetcher import (
    OBSERVATION_PAGE_SIZE,
    _auth_header,
    _extract_observations,
    _observations_from_trace,
    fetch_via_rest,
    fetch_via_sdk,
)


@dataclass
class ProbeStep:
    name: str
    method: str
    url: str
    params: dict[str, Any] = field(default_factory=dict)
    status_code: int | None = None
    ok: bool = False
    observation_count: int = 0
    error: str | None = None
    body_preview: str | None = None
    duration_ms: float = 0.0


def _mask_secret(value: str | None, visible: int = 6) -> str:
    if not value:
        return "<not set>"
    if len(value) <= visible:
        return "*" * len(value)
    return f"{value[:visible]}...{value[-4:]}"


def _preview_body(body: Any, limit: int = 300) -> str:
    try:
        text = json.dumps(body, default=str)
    except TypeError:
        text = str(body)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _request_step(
    client: httpx.Client,
    headers: dict[str, str],
    *,
    name: str,
    url: str,
    params: dict[str, Any] | None = None,
) -> ProbeStep:
    params = params or {}
    started = time.perf_counter()
    step = ProbeStep(name=name, method="GET", url=url, params=params)
    try:
        response = client.get(url, headers=headers, params=params)
        step.status_code = response.status_code
        step.duration_ms = (time.perf_counter() - started) * 1000
        if response.status_code == 200:
            body = response.json()
            observations = _extract_observations(body)
            if not observations and isinstance(body, dict):
                observations = _observations_from_trace(body)
            step.observation_count = len(observations)
            step.ok = True
            step.body_preview = _preview_body(body)
        else:
            step.error = response.text[:500] if response.text else f"HTTP {response.status_code}"
            step.body_preview = step.error
    except Exception as exc:
        step.duration_ms = (time.perf_counter() - started) * 1000
        step.error = str(exc)
        step.body_preview = step.error
    return step


def probe_langfuse(trace_id: str, base_url: str) -> list[ProbeStep]:
    base = base_url.rstrip("/")
    headers = _auth_header()
    time_window = {
        "fromStartTime": "2020-01-01T00:00:00.000Z",
        "toStartTime": "2030-12-31T23:59:59.999Z",
    }
    base_trace_filter = {"traceId": trace_id, "limit": OBSERVATION_PAGE_SIZE}

    probes: list[tuple[str, str, dict[str, Any] | None]] = [
        ("auth: projects", f"{base}/api/public/projects", None),
        ("trace: summary", f"{base}/api/public/traces/{trace_id}", None),
        (
            "trace: with observations",
            f"{base}/api/public/traces/{trace_id}",
            {"fields": "core,observations"},
        ),
        (
            "observations: v2 core+basic+io+usage",
            f"{base}/api/public/v2/observations",
            {**base_trace_filter, "fields": "core,basic,io,usage"},
        ),
        (
            "observations: v2 core+basic",
            f"{base}/api/public/v2/observations",
            {**base_trace_filter, "fields": "core,basic"},
        ),
        (
            "observations: v1 page=1",
            f"{base}/api/public/observations",
            {**base_trace_filter, "page": 1},
        ),
        (
            "observations: v1 page=1 + time window",
            f"{base}/api/public/observations",
            {**base_trace_filter, "page": 1, **time_window},
        ),
        (
            "observations: v1 legacy (limit=500, no page)",
            f"{base}/api/public/observations",
            {"traceId": trace_id, "limit": 500},
        ),
    ]

    steps: list[ProbeStep] = []
    with httpx.Client(timeout=30.0) as client:
        for name, url, params in probes:
            steps.append(_request_step(client, headers, name=name, url=url, params=params))
    return steps


def probe_sdk(trace_id: str) -> list[ProbeStep]:
    steps: list[ProbeStep] = []
    started = time.perf_counter()
    try:
        trace, observations = fetch_via_sdk(trace_id)
        steps.append(
            ProbeStep(
                name="sdk: fetch_via_sdk",
                method="SDK",
                url="langfuse.get_client()",
                ok=True,
                status_code=200,
                observation_count=len(observations),
                duration_ms=(time.perf_counter() - started) * 1000,
                body_preview=_preview_body(
                    {
                        "trace_keys": list(trace.keys()) if isinstance(trace, dict) else None,
                        "observation_sample": observations[:2],
                    }
                ),
            )
        )
    except Exception as exc:
        steps.append(
            ProbeStep(
                name="sdk: fetch_via_sdk",
                method="SDK",
                url="langfuse.get_client()",
                ok=False,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
                body_preview=str(exc),
            )
        )

    started = time.perf_counter()
    try:
        trace, observations = fetch_via_rest(trace_id)
        steps.append(
            ProbeStep(
                name="rest: fetch_via_rest",
                method="REST",
                url="fetch_via_rest()",
                ok=True,
                status_code=200,
                observation_count=len(observations),
                duration_ms=(time.perf_counter() - started) * 1000,
                body_preview=_preview_body(
                    {
                        "trace_keys": list(trace.keys()) if isinstance(trace, dict) else None,
                        "observation_sample": observations[:2],
                    }
                ),
            )
        )
    except Exception as exc:
        steps.append(
            ProbeStep(
                name="rest: fetch_via_rest",
                method="REST",
                url="fetch_via_rest()",
                ok=False,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
                body_preview=str(exc),
            )
        )
    return steps


def format_probe_url(step: ProbeStep) -> str:
    if step.params:
        return f"{step.url}?{urlencode(step.params)}"
    return step.url


def format_env_summary() -> dict[str, str]:
    import os

    return {
        "LANGFUSE_BASE_URL": os.getenv("LANGFUSE_BASE_URL", "<not set>"),
        "LANGFUSE_PUBLIC_KEY": _mask_secret(os.getenv("LANGFUSE_PUBLIC_KEY")),
        "LANGFUSE_SECRET_KEY": _mask_secret(os.getenv("LANGFUSE_SECRET_KEY")),
    }


