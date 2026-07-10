"""Data models for comparing verification results across multiple traces.

These models are the single source of truth ("what a comparison looks like")
consumed by every renderer (HTML today, potentially JSON/CSV later). Keeping
them free of rendering or fetching logic is what lets new renderers/sources be
added without touching this module (Open/Closed Principle).
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class GenerationSummary(BaseModel):
    """Drill-down detail for a single LLM call within a trace."""

    name: str | None = None
    agent_id: str | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


class PluginViolation(BaseModel):
    """One reason a plugin didn't score cleanly, kept with its own plugin
    (rather than in one flat report-wide list) so the UI can show *why* a
    specific check failed right next to that check."""

    code: str
    message: str
    resource: str | None = None
    """Matches a `PluginCheck.label` when this violation explains that specific
    check's failure (e.g. one resource, one budgeted metric) -- lets renderers
    avoid printing the same failure reason twice. `None` for violations that
    aren't about any single named check (e.g. input_context's unrelated-reads
    scope-creep warning, which spans all resources)."""


class PluginCheck(BaseModel):
    """One discrete thing a plugin evaluated (e.g. one resource's context
    grounding), shown regardless of whether it passed or failed. Unlike
    `PluginViolation` (only failures), this lets the drill-down show *what was
    validated* even when a plugin passes cleanly, instead of an empty section."""

    label: str
    passed: bool
    detail: str = ""


class PluginScore(BaseModel):
    """Drill-down detail for a single plugin's contribution to a trace's score."""

    plugin: str
    passed: bool
    score: float
    violations: list[PluginViolation] = Field(default_factory=list)
    checks: list[PluginCheck] = Field(default_factory=list)


class ComparisonRow(BaseModel):
    """One trace's worth of comparable metrics + drill-down detail."""

    trace_id: str
    status: str = "ok"
    """``"ok"`` or ``"error"`` (fetch/verification failed for this trace)."""
    error_message: str | None = None

    contract_id: str | None = None
    model_name: str | None = None
    user_id: str | None = None
    entry_agent: str | None = None
    session_id: str | None = None
    user_prompt: str | None = None
    """The trace's normalized input (`TraceSnapshot.user_prompt`) -- kept here so
    `filtered_by_user_prompt` can match on it client-side. Langfuse's trace-list
    API has no server-side filter for this (confirmed against a live instance --
    `column: "input"` is rejected as unmapped), so unlike `model_name` there's no
    way to push this filter down to the fetch itself."""
    skill_names: list[str] = Field(default_factory=list)
    """Every skill name loaded anywhere in the trace (flattened from
    `TraceSnapshot.skill_loads`), kept here so `filtered_by_skill_name` can
    match on it client-side -- like `user_prompt`, this isn't a native Langfuse
    column (it's derived during normalization from `load_skill` tool-call
    spans), so there's no server-side filter for it either."""

    duration_ms: int | None = None
    total_tokens: int | None = None
    total_cost_usd: float | None = None

    overall_score: float | None = None
    passed: bool | None = None

    plugin_scores: list[PluginScore] = Field(default_factory=list)
    """Each plugin's own score + the violations that explain it — the single
    source of truth for "why" a trace scored the way it did. There is
    intentionally no separate flat violations list: duplicating the same
    messages outside their plugin context is exactly the kind of noise that
    makes a report hard to read."""
    generations: list[GenerationSummary] = Field(default_factory=list)

    @property
    def is_error(self) -> bool:
        return self.status == "error"

    @property
    def violation_count(self) -> int:
        return sum(len(p.violations) for p in self.plugin_scores)


class ComparisonReport(BaseModel):
    """The full result of comparing N traces, possibly against several contracts."""

    contract_id: str
    """Display label: the single contract id, or a joined summary when several
    contracts were compared in one run (see `contract_ids` for the exact list)."""
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    rows: list[ComparisonRow] = Field(default_factory=list)

    @property
    def model_names(self) -> list[str]:
        return unique_in_order(row.model_name for row in self.rows)

    @property
    def contract_ids(self) -> list[str]:
        return unique_in_order(row.contract_id for row in self.rows)

    def filtered_by_model(self, model_name: str) -> "ComparisonReport":
        wanted = model_name.strip().lower()
        rows = [row for row in self.rows if (row.model_name or "").strip().lower() == wanted]
        return self.model_copy(update={"rows": rows})

    def filtered_by_user_prompt(self, search_text: str) -> "ComparisonReport":
        """Case-insensitive substring match against each row's `user_prompt`.

        Client-side by necessity -- see `ComparisonRow.user_prompt`'s docstring.
        """
        needle = search_text.strip().lower()
        rows = [row for row in self.rows if needle in (row.user_prompt or "").lower()]
        return self.model_copy(update={"rows": rows})

    def filtered_by_skill_name(self, search_text: str) -> "ComparisonReport":
        """Case-insensitive substring match against any of each row's
        `skill_names` entries.

        Client-side by necessity -- see `ComparisonRow.skill_names`'s docstring.
        """
        needle = search_text.strip().lower()
        rows = [row for row in self.rows if any(needle in skill.lower() for skill in row.skill_names)]
        return self.model_copy(update={"rows": rows})


def unique_in_order(values) -> list[str]:
    """Distinct, falsy-filtered values in first-seen order."""
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return list(seen.keys())
