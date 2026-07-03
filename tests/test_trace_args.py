import pytest

from wm_agents_validator.cli.trace_args import resolve_trace_from_args
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
