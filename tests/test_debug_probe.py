from unittest.mock import MagicMock, patch

from wm_agents_validator.trace.debug_probe import (
    ProbeStep,
    _mask_secret,
    format_probe_url,
    probe_langfuse,
)


def test_mask_secret():
    assert _mask_secret("pk-lf-abcdefghijklmnop") == "pk-lf-...mnop"


def test_format_probe_url():
    step = ProbeStep(
        name="test",
        method="GET",
        url="https://example.com/api",
        params={"traceId": "abc", "limit": 100},
    )
    assert format_probe_url(step) == "https://example.com/api?traceId=abc&limit=100"


@patch.dict(
    "os.environ",
    {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_BASE_URL": "https://langfuse.example.com",
    },
    clear=False,
)
def test_probe_langfuse_runs_all_steps():
    def handler(request):
        import httpx

        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json={"data": [{"id": "proj-1"}]})
        if request.url.path.endswith("/traces/trace-1"):
            return httpx.Response(200, json={"id": "trace-1", "observations": []})
        return httpx.Response(400, json={"message": "bad request"})

    mock_client = MagicMock()
    mock_client.__enter__.return_value = __import__("httpx").Client(
        transport=__import__("httpx").MockTransport(handler)
    )
    mock_client.__exit__.return_value = False

    with patch("wm_agents_validator.trace.debug_probe.httpx.Client", return_value=mock_client):
        steps = probe_langfuse("trace-1", "https://langfuse.example.com")

    assert len(steps) >= 2
    assert steps[0].name == "auth: projects"
    assert steps[0].ok is True
    assert steps[1].name == "trace: summary"
    assert steps[1].ok is True
