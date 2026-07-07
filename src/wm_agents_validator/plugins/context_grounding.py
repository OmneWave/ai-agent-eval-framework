from __future__ import annotations

import difflib
import json
from typing import Any

from wm_agents_validator.contracts.expressions import evaluate_skip_if, glob_match, resolve_path_template
from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation
from wm_agents_validator.models.trace_snapshot import (
    SpanRecord,
    TraceSnapshot,
    _span_base_name,
    extract_paths_from_input,
)
from wm_agents_validator.models.workflow_contract import WorkflowContract

SpanIndexEntry = tuple[SpanRecord, list[str], str, str]
"""(span, extracted_paths, input_blob, output_blob) -- input/output are separate
lowercased JSON blobs so a context term's presence can be attributed to the
tool call's arguments vs. its result, instead of one merged blob that hides
which side actually carried the context."""

# The tool whose entire purpose is pulling file content into the agent's
# context window. Search/scan tools (grep_in_files, find_files_by_glob) only
# touch a path as a *search scope*, not as retrieved context, so they're
# excluded from the unrelated-read check to avoid penalizing normal exploration.
_CONTEXT_READ_TOOL = "read_files"


def _paths_match(pattern: str, path: str) -> bool:
    """Compare a contract-declared path/pattern against an actually-read path,
    ignoring a leading '/' on either side. Tools sometimes report the same
    underlying file as project-relative ('services/...') and sometimes as
    absolute-looking ('/services/...'), so a leading slash (or lack of one) on
    either the contract side or the tool-call side must never by itself cause a
    false context_path_not_retrieved / unrelated_context_fetched violation.
    """
    norm_pattern = pattern.lstrip("/")
    norm_path = path.lstrip("/")
    return norm_path == norm_pattern or glob_match(norm_pattern, norm_path)


class ContextGroundingPlugin:
    """Checks whether the context an agent needed for a resource — its reference
    file(s) (``resource.files[].path``) and any declared context terms
    (``resource.context``) — was actually retrieved through a tool call, instead
    of being assumed, guessed, or hallucinated.

    Declared context terms are checked against *both* a tool call's input
    (arguments) and its output (result), since a term can legitimately surface
    either way -- e.g. an operation id the agent typed into a call's arguments,
    or a value that only came back in a lookup's result. A term missing from
    both sides is reported as a real deviation; the report also records which
    side(s) a found term actually came from, so "grounded via input" and
    "grounded via output" aren't conflated.

    For every active resource it compares what was *expected* to be read against
    what tool calls *actually* referenced anywhere in the trace, reports the
    resulting deviation with a concrete reason, and scores each resource by how
    much of its expected context was actually grounded in a real tool call.

    It also checks the inverse direction: files read via ``read_files`` that
    don't match *any* resource's declared file scope anywhere in the contract.
    This surfaces unrelated/unnecessary context being pulled into the agent's
    window (scope creep), and dilutes the overall score the same way
    ``intent_verification`` dilutes its score for extra skills loaded.
    """

    name = "context_grounding"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        ctx = context or EvalContext()
        span_index = self._build_span_index(snapshot)

        violations: list[Violation] = []
        resource_reports: dict[str, dict[str, Any]] = {}
        resource_scores: list[float] = []
        all_expected_patterns: list[str] = []

        for resource_name, resource in contract.resources.items():
            if evaluate_skip_if(resource.skip_if, ctx):
                continue
            expected_paths = [resolve_path_template(f.path, ctx) for f in resource.files]
            expected_context = list(resource.context)
            if not expected_paths and not expected_context:
                continue
            all_expected_patterns.extend(expected_paths)

            retrieved_paths, missing_paths, closest_match = self._check_paths(expected_paths, span_index)
            found_terms, missing_terms, context_locations = self._check_context_terms(
                expected_context, span_index
            )

            total = len(expected_paths) + len(expected_context)
            matched = len(retrieved_paths) + len(found_terms)
            resource_score = matched / total if total else 1.0
            resource_scores.append(resource_score)

            reasons: list[str] = []
            if missing_paths:
                hint = f" (closest tool read was: '{closest_match}')" if closest_match else " (no file reads observed at all)"
                reasons.append(f"expected file(s) never retrieved by any tool: {missing_paths}{hint}")
                violations.append(
                    Violation(
                        code="context_path_not_retrieved",
                        message=(
                            f"Resource '{resource_name}' expected to read {missing_paths} for context, "
                            f"but no tool call ever referenced it{hint}"
                        ),
                        plugin=self.name,
                        resource=resource_name,
                        evidence={
                            "expected_paths": expected_paths,
                            "missing_paths": missing_paths,
                            "closest_match": closest_match,
                        },
                    )
                )
            if missing_terms:
                reasons.append(
                    f"context term(s) never observed in any tool call's input or output: {missing_terms}"
                )
                violations.append(
                    Violation(
                        code="context_deviation",
                        message=(
                            f"Resource '{resource_name}' declares context {expected_context}, "
                            f"but {missing_terms} never showed up in any tool call's input or "
                            f"output — the agent's actual context appears to have drifted from "
                            f"what the task expected"
                        ),
                        plugin=self.name,
                        resource=resource_name,
                        evidence={
                            "expected_context": expected_context,
                            "missing_context": missing_terms,
                            "context_locations": context_locations,
                        },
                    )
                )

            resource_reports[resource_name] = {
                "expected_paths": expected_paths,
                "retrieved_paths": sorted(retrieved_paths),
                "missing_paths": missing_paths,
                "expected_context": expected_context,
                "found_context": found_terms,
                "missing_context": missing_terms,
                # Where each found term actually turned up: "input", "output",
                # or "input and output". Absent for terms in `missing_context`
                # since those were checked against both and found in neither.
                "context_locations": context_locations,
                "score": round(resource_score, 2),
                "reason": "; ".join(reasons) if reasons else "context fully grounded",
            }

        base_score = sum(resource_scores) / len(resource_scores) if resource_scores else 1.0

        allowed_read_patterns = [
            resolve_path_template(p, ctx) for p in contract.allowed_context_reads
        ]
        unrelated_reads = self._find_unrelated_reads(
            all_expected_patterns + allowed_read_patterns, span_index
        )
        total_expected_items = sum(
            len(r["expected_paths"]) + len(r["expected_context"]) for r in resource_reports.values()
        )
        # Mirror intent_verification's extra-item dilution: an unrelated read doesn't
        # fail the check outright, but it dilutes the score the same way an unexpected
        # skill load does, since it's evidence of scope creep / wasted context budget.
        denominator = total_expected_items + len(unrelated_reads)
        penalty_factor = total_expected_items / denominator if denominator else 1.0
        score = base_score * penalty_factor

        unrelated_label = "unrelated reads"
        if unrelated_reads:
            unrelated_detail = f"scope creep -- read but not declared for any resource: {unrelated_reads}"
            violations.append(
                Violation(
                    code="unrelated_context_fetched",
                    message=(
                        f"File(s) read that aren't declared as context/target for any resource: "
                        f"{unrelated_reads}"
                    ),
                    plugin=self.name,
                    resource=unrelated_label,
                    evidence={
                        "unrelated_paths": unrelated_reads,
                        "expected_patterns": sorted(set(all_expected_patterns)),
                        "allowed_context_reads": sorted(set(allowed_read_patterns)),
                    },
                )
            )
        else:
            unrelated_detail = "no unrelated files read"

        # Missing the reference file entirely is a hard failure (context was never grounded);
        # a declared context term not surfacing anywhere, or an unrelated file being read,
        # is a softer signal of drift and only dents the score, mirroring how
        # intent_verification treats extra/missing skills.
        passed = all(not r["missing_paths"] for r in resource_reports.values())

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=round(score, 4),
            violations=violations,
            evidence={
                "resources": resource_reports,
                "unrelated_reads": unrelated_reads,
                # Standard "checks" contract (see PluginResult docs): one entry
                # per named thing this plugin evaluated, pass or fail, so a
                # generic renderer can show the full breakdown without knowing
                # anything about "resources" specifically.
                "checks": {
                    **{
                        name: {"passed": r["score"] >= 1.0, "detail": r["reason"]}
                        for name, r in resource_reports.items()
                    },
                    # Surfaced as its own check (not folded into a resource) since
                    # scope creep isn't about any single resource -- it's what
                    # explains a score below 100% even when every resource above
                    # shows "context fully grounded".
                    unrelated_label: {"passed": not unrelated_reads, "detail": unrelated_detail},
                },
            },
        )

    def _find_unrelated_reads(
        self, expected_patterns: list[str], span_index: list[SpanIndexEntry]
    ) -> list[str]:
        """Files pulled into context via read_files that match no resource's file scope."""
        seen: set[str] = set()
        unrelated: set[str] = set()
        for span, paths, _input_blob, _output_blob in span_index:
            if _span_base_name(span.name) != _CONTEXT_READ_TOOL:
                continue
            for path in paths:
                if path in seen:
                    continue
                seen.add(path)
                if not any(_paths_match(pattern, path) for pattern in expected_patterns):
                    unrelated.add(path)
        return sorted(unrelated)

    def _build_span_index(self, snapshot: TraceSnapshot) -> list[SpanIndexEntry]:
        index: list[SpanIndexEntry] = []
        for span in snapshot.spans:
            if span.type != "TOOL":
                continue
            paths = extract_paths_from_input(span.input or {}, _span_base_name(span.name))
            input_blob = json.dumps(span.input or {}, default=str).lower()
            output_blob = json.dumps(span.output, default=str).lower() if span.output is not None else ""
            index.append((span, paths, input_blob, output_blob))
        return index

    def _check_paths(
        self, expected_paths: list[str], span_index: list[SpanIndexEntry]
    ) -> tuple[set[str], list[str], str | None]:
        all_seen_paths = [p for _, paths, _, _ in span_index for p in paths]
        retrieved = {
            expected
            for expected in expected_paths
            if any(_paths_match(expected, seen) for seen in all_seen_paths)
        }
        missing = [p for p in expected_paths if p not in retrieved]

        closest_match = None
        if missing and all_seen_paths:
            best_ratio = 0.0
            for expected in missing:
                for seen in all_seen_paths:
                    ratio = difflib.SequenceMatcher(
                        None, expected.lstrip("/"), seen.lstrip("/")
                    ).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        closest_match = seen
        return retrieved, missing, closest_match

    def _check_context_terms(
        self, expected_context: list[str], span_index: list[SpanIndexEntry]
    ) -> tuple[list[str], list[str], dict[str, str]]:
        """A term counts as grounded if it shows up in a tool call's input
        *or* its output -- either is legitimate evidence the agent actually
        engaged with that context, not just the input side. ``locations``
        records exactly which side(s) each found term came from, so the
        report can distinguish "the agent referenced this" (input) from
        "this only ever came back in a result" (output) instead of hiding
        that distinction behind a flat found/missing bit.
        """
        found: list[str] = []
        missing: list[str] = []
        locations: dict[str, str] = {}
        for term in expected_context:
            needle = term.lower()
            in_input = any(needle in input_blob for _, _, input_blob, _ in span_index)
            in_output = any(needle in output_blob for _, _, _, output_blob in span_index)
            if in_input and in_output:
                found.append(term)
                locations[term] = "input and output"
            elif in_input:
                found.append(term)
                locations[term] = "input only"
            elif in_output:
                found.append(term)
                locations[term] = "output only"
            else:
                missing.append(term)
        return found, missing, locations
