"""Strategies for discovering *which* trace IDs to feed into a comparison run.

Each source has the single responsibility of producing a list of trace IDs.
`ComparisonPipeline` depends only on the `TraceSource` protocol (Dependency
Inversion), so new discovery strategies (by session, by tag, ...) can be added
without changing the pipeline (Open/Closed).
"""
from __future__ import annotations

import hashlib
import re
from typing import Protocol, runtime_checkable

from wm_agents_validator.controller.fetch import fetch_and_normalize
from wm_agents_validator.trace.fetcher import (
    iter_trace_id_pages,
    list_trace_ids_in_range,
    search_trace_ids_by_metadata,
)

_WHITESPACE_RE = re.compile(r"\s+")


def make_user_prompt_key(user_prompt: str) -> str:
    """Deterministic key for an exact `user_prompt`, for correlating traces
    that ran the identical task (e.g. the same benchmark prompt against
    different models) via a `metadata.userPromptKey` filter.

    This is an exact-match key, not a content/substring search -- Langfuse's
    metadata filter matches the *stored* value verbatim, and the stored value
    here is a hash of the whole normalized prompt. For "does this trace's
    prompt contain X", use `ComparisonReport.filtered_by_user_prompt` instead
    (client-side; see its docstring for why there's no server-side option).

    The ingestion side (wherever traces are created, e.g. wm-agent-server's
    Langfuse instrumentation) must call this *same* function when writing
    `metadata={"userPromptKey": make_user_prompt_key(user_prompt)}`, or the
    hashes won't line up and `UserPromptTraceSource` will never match.
    """
    normalized = _WHITESPACE_RE.sub(" ", user_prompt.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
        environment: str | None = None,
    ) -> None:
        self._from_timestamp = from_timestamp
        self._to_timestamp = to_timestamp
        self._user_id = user_id
        self._limit = limit
        self._environment = environment

    def get_trace_ids(self) -> list[str]:
        return list_trace_ids_in_range(
            self._from_timestamp,
            self._to_timestamp,
            user_id=self._user_id,
            limit=self._limit,
            environment=self._environment,
        )


def _build_metadata_filter_conditions(metadata_filters: list[tuple[str, str]]) -> list[dict]:
    """Groups (key, value) pairs by key, then builds one Langfuse filter
    condition per key -- DIFFERENT keys still AND (e.g. projectid=X AND
    environment=stage-ai), but the SAME key repeated (e.g. two
    `--filter projectid=` occurrences) becomes an OR across those values,
    not an impossible AND. A single value per key keeps using the exact-match
    `stringObject`/`"="` condition (unchanged from before); a key with more
    than one value switches to `categoryOptions`/`"any of"` -- confirmed via
    the langfuse SDK's own `trace.list()` filter-JSON docstring as the
    supported way to OR multiple values for one nested metadata key (the
    plain `stringObject` type only offers `=`/`contains`/etc., no "any of").
    """
    values_by_key: dict[str, list[str]] = {}
    for key, value in metadata_filters:
        values_by_key.setdefault(key, []).append(value)
    conditions: list[dict] = []
    for key, values in values_by_key.items():
        if len(values) == 1:
            conditions.append({"type": "stringObject", "column": "metadata", "key": key, "operator": "=", "value": values[0]})
        else:
            conditions.append(
                {"type": "categoryOptions", "column": "metadata", "key": key, "operator": "any of", "value": values}
            )
    return conditions


class MetadataFilterTraceSource:
    """Discovers up to `limit` trace IDs whose metadata matches all given
    key=value conditions, applied server-side via Langfuse's filter JSON --
    see `search_trace_ids_by_metadata` and `_build_metadata_filter_conditions`
    for how repeated keys OR instead of ANDing into an impossible condition.
    Standalone -- no time range needed.
    """

    def __init__(
        self,
        metadata_filters: list[tuple[str, str]],
        *,
        limit: int = 50,
        environment: str | None = None,
    ) -> None:
        if not metadata_filters:
            raise ValueError("metadata_filters must be a non-empty list")
        self._filters = _build_metadata_filter_conditions(metadata_filters)
        self._limit = limit
        self._environment = environment

    def get_trace_ids(self) -> list[str]:
        return search_trace_ids_by_metadata(
            self._filters, limit=self._limit, environment=self._environment
        )


class ContentSearchTraceSource:
    """Discovers up to `limit` trace IDs whose content matches given
    predicates (`user_prompt`/`skill_names`), by paging through the most
    recent traces (no time bound, `page_size` at a time), fetching +
    normalizing each candidate to inspect its content, and stopping once
    `limit` matches are found -- or `max_candidates` have been scanned,
    whichever comes first.

    Unlike `MetadataFilterTraceSource`/`UserPromptTraceSource`, this can't
    push the check to Langfuse's server -- `user_prompt`/`skill_names` aren't
    filterable columns (see their docstrings) -- so it does real work per
    candidate: a fetch + normalize (not the full contract-verification
    pipeline) to inspect `TraceSnapshot.user_prompt`/`.skill_loads`. Matched
    trace IDs still get re-fetched later by `ComparisonPipeline`'s own
    `evaluate()` step -- that redundant fetch is the price of only paying for
    a *fetch* (not full plugin verification) against the candidates that
    don't match, which is still cheaper than the `--from`/`--to` +
    `--user-prompt-contains` combo (that one verifies every candidate,
    including near-certain rejects).
    """

    def __init__(
        self,
        *,
        user_prompt_contains: str | None = None,
        skill_name_contains: str | None = None,
        limit: int = 50,
        page_size: int = 20,
        environment: str | None = None,
        max_candidates: int = 500,
    ) -> None:
        if not user_prompt_contains and not skill_name_contains:
            raise ValueError("at least one of user_prompt_contains/skill_name_contains is required")
        self._user_prompt_needle = user_prompt_contains.strip().lower() if user_prompt_contains else None
        self._skill_needle = skill_name_contains.strip().lower() if skill_name_contains else None
        self._limit = limit
        self._page_size = max(page_size, 1)
        self._environment = environment
        self._max_candidates = max_candidates

    def _matches(self, snapshot) -> bool:
        if self._user_prompt_needle is not None:
            if self._user_prompt_needle not in (snapshot.user_prompt or "").lower():
                return False
        if self._skill_needle is not None:
            skill_names = [name for load in snapshot.skill_loads for name in load.skill_names]
            if not any(self._skill_needle in name.lower() for name in skill_names):
                return False
        return True

    def get_trace_ids(self) -> list[str]:
        matched: list[str] = []
        scanned = 0
        max_pages = max(1, -(-self._max_candidates // self._page_size))  # ceil division
        print(
            f"Content search: scanning up to {self._max_candidates} candidate(s) "
            f"({self._page_size} per fetch) for {self._limit} match(es)..."
        )
        for page in iter_trace_id_pages(
            page_size=self._page_size, environment=self._environment, max_pages=max_pages
        ):
            for trace_id in page:
                if len(matched) >= self._limit or scanned >= self._max_candidates:
                    print(
                        f"Content search done: scanned {scanned} candidate(s), "
                        f"found {len(matched)} match(es): {matched}"
                    )
                    return matched
                scanned += 1
                try:
                    snapshot = fetch_and_normalize(trace_id).snapshot
                except Exception as exc:  # noqa: BLE001 - one bad candidate shouldn't kill the search
                    print(f"  [{scanned}] {trace_id}: fetch failed ({exc}) -- skipped")
                    continue
                if self._matches(snapshot):
                    matched.append(trace_id)
                    print(f"  [{scanned}] {trace_id}: MATCH ({len(matched)}/{self._limit})")
                else:
                    print(f"  [{scanned}] {trace_id}: no match")
        print(
            f"Content search done: scanned {scanned} candidate(s), "
            f"found {len(matched)} match(es): {matched}"
        )
        return matched


class UserPromptTraceSource:
    """Discovers up to `limit` trace IDs that ran the exact given `user_prompt`,
    via a single `metadata.userPromptKey` filter (server-side, exact match).

    Only finds traces created *after* ingestion starts writing
    `metadata={"userPromptKey": make_user_prompt_key(user_prompt)}` -- not
    retroactive, and only matches an identical (normalized) prompt, not a
    substring. See `make_user_prompt_key`'s docstring for both caveats and for
    what to use instead if you want substring/content search.

    Example:
        source = UserPromptTraceSource(
            "Bind swagger_findPetsByTagsTable1 widget in PetTable page to get "
            "/petstore/pet/findByTags endpoint using petstore service",
            environment="default",
            limit=50,
        )
        trace_ids = source.get_trace_ids()
    """

    def __init__(
        self,
        user_prompt: str,
        *,
        limit: int = 50,
        environment: str | None = None,
    ) -> None:
        if not user_prompt or not user_prompt.strip():
            raise ValueError("user_prompt must not be empty")
        self._filters = [
            {
                "type": "stringObject",
                "column": "metadata",
                "key": "userPromptKey",
                "operator": "=",
                "value": make_user_prompt_key(user_prompt),
            }
        ]
        self._limit = limit
        self._environment = environment

    def get_trace_ids(self) -> list[str]:
        return search_trace_ids_by_metadata(
            self._filters, limit=self._limit, environment=self._environment
        )
