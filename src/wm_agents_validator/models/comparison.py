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


def unique_in_order(values) -> list[str]:
    """Distinct, falsy-filtered values in first-seen order."""
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return list(seen.keys())
