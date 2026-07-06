"""Strategies for discovering *which* trace IDs to feed into a comparison run.

Each source has the single responsibility of producing a list of trace IDs.
`ComparisonPipeline` depends only on the `TraceSource` protocol (Dependency
Inversion), so new discovery strategies (by session, by tag, ...) can be added
without changing the pipeline (Open/Closed).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from wm_agents_validator.trace.fetcher import list_trace_ids_in_range


@runtime_checkable
class TraceSource(Protocol):
    """Anything that can produce a list of Langfuse trace IDs to compare."""

    def get_trace_ids(self) -> list[str]: ...


class ExplicitTraceIdSource:
    """Wraps a caller-supplied list of trace IDs (e.g. from `--trace-ids`)."""

    def __init__(self, trace_ids: list[str]) -> None:
        if not trace_ids:
            raise ValueError("trace_ids must be a non-empty list")
        self._trace_ids = list(trace_ids)

    def get_trace_ids(self) -> list[str]:
        return list(self._trace_ids)


class TimeRangeTraceSource:
    """Discovers trace IDs created within [from_timestamp, to_timestamp].

    `user_id` is passed straight through to Langfuse's native `userId` trace
    filter. Model-name filtering isn't offered here because model is only
    known after a trace is fetched/normalized; see `ComparisonPipeline`'s
    `model_filter` for that.
    """

    def __init__(
        self,
        from_timestamp: str,
        to_timestamp: str,
        *,
        user_id: str | None = None,
        limit: int = 50,
    ) -> None:
        self._from_timestamp = from_timestamp
        self._to_timestamp = to_timestamp
        self._user_id = user_id
        self._limit = limit

    def get_trace_ids(self) -> list[str]:
        return list_trace_ids_in_range(
            self._from_timestamp,
            self._to_timestamp,
            user_id=self._user_id,
            limit=self._limit,
        )
