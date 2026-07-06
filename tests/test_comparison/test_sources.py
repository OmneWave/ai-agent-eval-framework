from unittest.mock import patch

import pytest

from wm_agents_validator.comparison.sources import ExplicitTraceIdSource, TimeRangeTraceSource


def test_explicit_trace_id_source_returns_given_ids():
    source = ExplicitTraceIdSource(["a", "b", "c"])
    assert source.get_trace_ids() == ["a", "b", "c"]


def test_explicit_trace_id_source_returns_a_copy_not_the_original_list():
    original = ["a", "b"]
    source = ExplicitTraceIdSource(original)
    result = source.get_trace_ids()
    result.append("mutated")
    assert source.get_trace_ids() == ["a", "b"]


def test_explicit_trace_id_source_rejects_empty_list():
    with pytest.raises(ValueError):
        ExplicitTraceIdSource([])


def test_time_range_trace_source_delegates_to_fetcher():
    with patch(
        "wm_agents_validator.comparison.sources.list_trace_ids_in_range",
        return_value=["t1", "t2"],
    ) as mock_list:
        source = TimeRangeTraceSource(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", user_id="alice", limit=10
        )
        result = source.get_trace_ids()

    assert result == ["t1", "t2"]
    mock_list.assert_called_once_with(
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", user_id="alice", limit=10
    )
