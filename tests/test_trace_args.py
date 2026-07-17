import pytest

from wm_agents_validator.cli.trace_args import parse_metadata_filters, resolve_trace_from_args
from wm_agents_validator.trace.resolver import resolve_trace_id


def test_resolve_trace_id_direct():
    assert resolve_trace_id("abc123") == "abc123"


def test_resolve_trace_id_from_thread_run():
    from langfuse import Langfuse

    tid = resolve_trace_id("", "proj:session", "run-abc")
    expected = Langfuse.create_trace_id(seed="proj:session:run-abc")
    assert tid == expected


def test_resolve_trace_from_args_direct():
    args = _ns(trace_id="abc123", thread_id="", run_id="")
    assert resolve_trace_from_args(args) == "abc123"


def test_resolve_trace_from_args_missing():
    args = _ns(trace_id="", thread_id="", run_id="")
    with pytest.raises(SystemExit):
        resolve_trace_from_args(args)


def _ns(**kwargs):
    from argparse import Namespace

    return Namespace(**kwargs)


def test_parse_metadata_filters_happy_path():
    assert parse_metadata_filters(["workflow_name=foo", "model_name=glm-5"]) == [
        ("workflow_name", "foo"),
        ("model_name", "glm-5"),
    ]


def test_parse_metadata_filters_strips_whitespace():
    assert parse_metadata_filters([" workflow_name = foo "]) == [("workflow_name", "foo")]


def test_parse_metadata_filters_rejects_missing_equals():
    with pytest.raises(ValueError):
        parse_metadata_filters(["workflow_name"])


def test_parse_metadata_filters_rejects_empty_key_or_value():
    with pytest.raises(ValueError):
        parse_metadata_filters(["=foo"])
    with pytest.raises(ValueError):
        parse_metadata_filters(["workflow_name="])
