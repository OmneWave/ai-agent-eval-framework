from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.plugins.timing import (
    fmt_ms,
    parse_timestamp,
    span_duration_ms,
    sum_duration_ms,
)


def test_parse_timestamp_handles_z_suffix():
    assert parse_timestamp("2026-01-01T10:00:00Z") is not None


def test_parse_timestamp_returns_none_for_missing_or_invalid():
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("not-a-timestamp") is None


def test_span_duration_ms_computes_delta():
    span = SpanRecord(
        id="s1", name="read_files", type="TOOL",
        timestamp="2026-01-01T10:00:00Z", end_time="2026-01-01T10:00:02.5Z",
    )
    assert span_duration_ms(span) == 2500.0


def test_span_duration_ms_none_when_end_time_missing():
    span = SpanRecord(id="s1", name="read_files", type="TOOL", timestamp="2026-01-01T10:00:00Z")
    assert span_duration_ms(span) is None


def test_sum_duration_ms_ignores_spans_with_unknown_duration():
    spans = [
        SpanRecord(id="s1", name="a", type="TOOL", timestamp="2026-01-01T10:00:00Z", end_time="2026-01-01T10:00:01Z"),
        SpanRecord(id="s2", name="b", type="TOOL", timestamp="2026-01-01T10:00:00Z"),  # no end_time
    ]
    assert sum_duration_ms(spans) == 1000.0


def test_fmt_ms_formats_with_thousands_separator():
    assert fmt_ms(1234.0) == "1,234ms"
    assert fmt_ms(None) == "n/a"
