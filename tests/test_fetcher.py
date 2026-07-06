from unittest.mock import MagicMock, patch

import httpx

from wm_agents_validator.trace.fetcher import (
    _extract_observations,
    _fetch_observations_rest,
    _observations_from_trace,
    fetch_via_rest,
    list_trace_ids_in_range,
)


def test_extract_observations_from_data_wrapper():
    body = {"data": [{"id": "obs-1", "name": "load_skill"}]}
    assert _extract_observations(body) == [{"id": "obs-1", "name": "load_skill"}]


def test_observations_from_trace():
    trace = {"id": "trace-1", "observations": [{"id": "obs-1"}]}
    assert _observations_from_trace(trace) == [{"id": "obs-1"}]


def test_fetch_observations_rest_falls_back_from_v1_400_to_trace_embedded():
    trace = {"id": "trace-1", "name": "agent-run"}
    embedded_trace = {
        "id": "trace-1",
        "observations": [{"id": "obs-1", "name": "load_skill", "type": "SPAN"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/public/v2/observations"):
            return httpx.Response(404, json={"message": "not found"})
        if request.url.path.endswith("/api/public/observations"):
            return httpx.Response(400, json={"message": "bad request"})
        if request.url.path.endswith("/api/public/traces/trace-1"):
            params = dict(request.url.params)
            if params.get("fields") == "core,observations":
                return httpx.Response(200, json=embedded_trace)
            return httpx.Response(200, json=trace)
        return httpx.Response(404, json={"message": "not found"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    observations = _fetch_observations_rest(
        client,
        "https://langfuse.example.com",
        {"Authorization": "Basic test"},
        "trace-1",
        trace,
    )
    client.close()

    assert observations == embedded_trace["observations"]


@patch.dict(
    "os.environ",
    {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_BASE_URL": "https://langfuse.example.com",
    },
    clear=False,
)
def test_fetch_via_rest_uses_v1_paginated_observations():
    trace = {"id": "trace-1"}
    observations_page = {"data": [{"id": "obs-1", "name": "load_skill", "type": "SPAN"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/public/traces/trace-1"):
            return httpx.Response(200, json=trace)
        if request.url.path.endswith("/api/public/v2/observations"):
            return httpx.Response(400, json={"message": "bad request"})
        if request.url.path.endswith("/api/public/observations"):
            params = dict(request.url.params)
            if params.get("page") == "1":
                return httpx.Response(200, json=observations_page)
            return httpx.Response(400, json={"message": "bad request"})
        return httpx.Response(404, json={"message": "not found"})

    mock_client = MagicMock()
    mock_client.__enter__.return_value = httpx.Client(transport=httpx.MockTransport(handler))
    mock_client.__exit__.return_value = False

    with patch("wm_agents_validator.trace.fetcher.httpx.Client", return_value=mock_client):
        fetched_trace, observations = fetch_via_rest("trace-1")

    assert fetched_trace == trace
    assert observations == observations_page["data"]


@patch.dict(
    "os.environ",
    {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_BASE_URL": "https://langfuse.example.com",
    },
    clear=False,
)
def test_list_trace_ids_in_range_paginates_until_limit():
    page1 = {"data": [{"id": f"trace-{i}"} for i in range(2)]}
    page2 = {"data": [{"id": "trace-2"}]}
    seen_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen_params.append(params)
        if params.get("page") == "1":
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json=page2)

    with patch(
        "wm_agents_validator.trace.fetcher.httpx.Client",
        return_value=httpx.Client(transport=httpx.MockTransport(handler)),
    ):
        trace_ids = list_trace_ids_in_range(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", limit=2
        )

    assert trace_ids == ["trace-0", "trace-1"]
    assert seen_params[0]["fromTimestamp"] == "2026-01-01T00:00:00Z"
    assert seen_params[0]["toTimestamp"] == "2026-01-02T00:00:00Z"
    # Stops after the first page since we already hit the requested limit.
    assert len(seen_params) == 1


@patch.dict(
    "os.environ",
    {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_BASE_URL": "https://langfuse.example.com",
    },
    clear=False,
)
def test_list_trace_ids_in_range_passes_user_id_filter():
    captured_params: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_params.update(dict(request.url.params))
        return httpx.Response(200, json={"data": []})

    with patch(
        "wm_agents_validator.trace.fetcher.httpx.Client",
        return_value=httpx.Client(transport=httpx.MockTransport(handler)),
    ):
        trace_ids = list_trace_ids_in_range(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", user_id="alice", limit=5
        )

    assert trace_ids == []
    assert captured_params["userId"] == "alice"
