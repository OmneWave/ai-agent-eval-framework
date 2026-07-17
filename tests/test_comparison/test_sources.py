import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from wm_agents_validator.comparison.sources import (
    ContentSearchTraceSource,
    ExplicitTraceIdSource,
    MetadataFilterTraceSource,
    TimeRangeTraceSource,
    UserPromptTraceSource,
    make_user_prompt_key,
)


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
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", user_id="alice", limit=10, environment="stage-ai"
        )
        result = source.get_trace_ids()

    assert result == ["t1", "t2"]
    mock_list.assert_called_once_with(
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", user_id="alice", limit=10, environment="stage-ai"
    )


def test_metadata_filter_trace_source_delegates_to_fetcher():
    with patch(
        "wm_agents_validator.comparison.sources.search_trace_ids_by_metadata",
        return_value=["t1"],
    ) as mock_search:
        source = MetadataFilterTraceSource(
            [("workflow_name", "foo"), ("model_name", "glm-5")], limit=20, environment="stage-ai"
        )
        result = source.get_trace_ids()

    assert result == ["t1"]
    expected_filters = [
        {"type": "stringObject", "column": "metadata", "key": "workflow_name", "operator": "=", "value": "foo"},
        {"type": "stringObject", "column": "metadata", "key": "model_name", "operator": "=", "value": "glm-5"},
    ]
    mock_search.assert_called_once_with(expected_filters, limit=20, environment="stage-ai")


def test_metadata_filter_trace_source_ors_repeated_key_instead_of_anding():
    # Two --filter projectid=X occurrences must OR across those values --
    # ANDing them (the old behavior) can never match, since one trace's
    # metadata.projectid can only equal one value at a time.
    with patch(
        "wm_agents_validator.comparison.sources.search_trace_ids_by_metadata",
        return_value=["t1"],
    ) as mock_search:
        source = MetadataFilterTraceSource(
            [("projectid", "WMPRJ1"), ("projectid", "WMPRJ2"), ("environment", "stage-ai")],
            limit=1,
        )
        source.get_trace_ids()

    expected_filters = [
        {"type": "categoryOptions", "column": "metadata", "key": "projectid", "operator": "any of", "value": ["WMPRJ1", "WMPRJ2"]},
        {"type": "stringObject", "column": "metadata", "key": "environment", "operator": "=", "value": "stage-ai"},
    ]
    mock_search.assert_called_once_with(expected_filters, limit=1, environment=None)


def test_metadata_filter_trace_source_rejects_empty_list():
    with pytest.raises(ValueError):
        MetadataFilterTraceSource([])


def test_make_user_prompt_key_is_deterministic():
    prompt = "Bind widget in PetTable to findByTags endpoint"
    assert make_user_prompt_key(prompt) == make_user_prompt_key(prompt)


def test_make_user_prompt_key_matches_expected_sha256_of_normalized_prompt():
    key = make_user_prompt_key("  Bind   widget\nin PetTable  ")
    expected = hashlib.sha256(b"Bind widget in PetTable").hexdigest()
    assert key == expected


def test_make_user_prompt_key_normalizes_whitespace_variants_the_same():
    assert make_user_prompt_key("Bind widget  in\nPetTable") == make_user_prompt_key("Bind widget in PetTable")


def test_make_user_prompt_key_differs_for_different_prompts():
    assert make_user_prompt_key("prompt one") != make_user_prompt_key("prompt two")


def test_user_prompt_trace_source_delegates_to_fetcher():
    prompt = "Bind swagger_findPetsByTagsTable1 widget in PetTable page"
    with patch(
        "wm_agents_validator.comparison.sources.search_trace_ids_by_metadata",
        return_value=["t1"],
    ) as mock_search:
        source = UserPromptTraceSource(prompt, limit=20, environment="stage-ai")
        result = source.get_trace_ids()

    assert result == ["t1"]
    expected_filters = [
        {
            "type": "stringObject",
            "column": "metadata",
            "key": "userPromptKey",
            "operator": "=",
            "value": make_user_prompt_key(prompt),
        }
    ]
    mock_search.assert_called_once_with(expected_filters, limit=20, environment="stage-ai")


def test_user_prompt_trace_source_rejects_empty_prompt():
    with pytest.raises(ValueError):
        UserPromptTraceSource("")
    with pytest.raises(ValueError):
        UserPromptTraceSource("   ")


def _fake_snapshot(user_prompt="", skill_names=None):
    skill_loads = [SimpleNamespace(skill_names=skill_names or [])]
    return SimpleNamespace(user_prompt=user_prompt, skill_loads=skill_loads)


def _fake_fetch_result(snapshot):
    return SimpleNamespace(snapshot=snapshot)


def test_content_search_trace_source_rejects_no_predicates():
    with pytest.raises(ValueError):
        ContentSearchTraceSource()


def test_content_search_trace_source_stops_once_limit_matches_found():
    candidates = {
        "t1": _fake_snapshot(user_prompt="Bind widget to findByTags"),
        "t2": _fake_snapshot(user_prompt="Create a CustomerTable page"),
        "t3": _fake_snapshot(user_prompt="Another findByTags run"),
        "t4": _fake_snapshot(user_prompt="findByTags again, never reached"),
    }

    def fake_fetch_and_normalize(trace_id):
        return _fake_fetch_result(candidates[trace_id])

    with (
        patch(
            "wm_agents_validator.comparison.sources.iter_trace_id_pages",
            return_value=[["t1", "t2", "t3", "t4"]],
        ),
        patch(
            "wm_agents_validator.comparison.sources.fetch_and_normalize",
            side_effect=fake_fetch_and_normalize,
        ) as mock_fetch,
    ):
        source = ContentSearchTraceSource(user_prompt_contains="findbytags", limit=2)
        result = source.get_trace_ids()

    assert result == ["t1", "t3"]
    # Stops as soon as 2 matches are found -- t4 is never even fetched.
    assert mock_fetch.call_count == 3


def test_content_search_trace_source_requires_all_predicates_to_match():
    snapshot = _fake_snapshot(user_prompt="Bind widget to findByTags", skill_names=["explore-api"])

    with (
        patch(
            "wm_agents_validator.comparison.sources.iter_trace_id_pages",
            return_value=[["t1"]],
        ),
        patch(
            "wm_agents_validator.comparison.sources.fetch_and_normalize",
            return_value=_fake_fetch_result(snapshot),
        ),
    ):
        source = ContentSearchTraceSource(
            user_prompt_contains="findbytags", skill_name_contains="ui_to_api_binding", limit=5
        )
        result = source.get_trace_ids()

    assert result == []  # prompt matches, but skill name doesn't -- both must match


def test_content_search_trace_source_skips_candidates_that_fail_to_fetch():
    def fake_fetch_and_normalize(trace_id):
        if trace_id == "bad":
            raise RuntimeError("fetch failed")
        return _fake_fetch_result(_fake_snapshot(user_prompt="findByTags"))

    with (
        patch(
            "wm_agents_validator.comparison.sources.iter_trace_id_pages",
            return_value=[["bad", "good"]],
        ),
        patch(
            "wm_agents_validator.comparison.sources.fetch_and_normalize",
            side_effect=fake_fetch_and_normalize,
        ),
    ):
        source = ContentSearchTraceSource(user_prompt_contains="findbytags", limit=5)
        result = source.get_trace_ids()

    assert result == ["good"]


def test_content_search_trace_source_stops_at_max_candidates():
    def fake_fetch_and_normalize(trace_id):
        return _fake_fetch_result(_fake_snapshot(user_prompt="never matches"))

    with (
        patch(
            "wm_agents_validator.comparison.sources.iter_trace_id_pages",
            return_value=[["t1", "t2", "t3"]],
        ),
        patch(
            "wm_agents_validator.comparison.sources.fetch_and_normalize",
            side_effect=fake_fetch_and_normalize,
        ) as mock_fetch,
    ):
        source = ContentSearchTraceSource(user_prompt_contains="findbytags", limit=5, max_candidates=2)
        result = source.get_trace_ids()

    assert result == []
    assert mock_fetch.call_count == 2
