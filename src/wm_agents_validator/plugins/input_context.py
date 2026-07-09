from __future__ import annotations

import difflib
import json

from wm_agents_validator.contracts.expressions import glob_match
from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation, score_from_checks
from wm_agents_validator.models.trace_snapshot import (
    SpanRecord,
    TraceSnapshot,
    _span_base_name,
    extract_paths_from_input,
)
from wm_agents_validator.models.workflow_contract import WorkflowContract

SpanIndexEntry = tuple[SpanRecord, list[str], str, str]
"""(span, extracted_paths, input_blob, output_blob) -- input/output are separate
lowercased JSON blobs so a term's presence can be attributed to the tool call's
arguments vs. its result, instead of one merged blob that hides which side
actually carried it."""

# The tool whose entire purpose is pulling file content into the agent's
# context window. Search/scan tools (grep_in_files, find_files_by_glob) only
# touch a path as a *search scope*, not as retrieved context, so they're
# excluded from the unrelated-read check to avoid penalizing normal exploration.
_CONTEXT_READ_TOOL = "read_files"


def _paths_match(pattern: str, path: str) -> bool:
    """Compare a resolved resource path against an actually-read path, ignoring
    a leading '/' on either side. Tools sometimes report the same underlying
    file as project-relative ('services/...') and sometimes as absolute-looking
    ('/services/...'), so a leading slash on either side must never by itself
    cause a false context_path_not_retrieved / unrelated_context_fetched.
    """
    norm_pattern = pattern.lstrip("/")
    norm_path = path.lstrip("/")
    return norm_path == norm_pattern or glob_match(norm_pattern, norm_path)


class InputContextPlugin:
    """Checks whether the context an agent needed -- each ``input_context[]``
    entry's resolved resource path, plus its declared ``terms`` and any
    qualifier terms parsed out of the reference itself -- was actually
    retrieved through a tool call, instead of being assumed, guessed, or
    hallucinated.

    Qualifier terms parsed from ``output[]`` references are checked here too
    (not by the ``output`` plugin, which has no content-relevance check of its
    own), under a separate rollup.

    It also checks the inverse direction: files read via ``read_files`` that
    don't match any resource declared under ``input_context`` or ``output``
    (nor exempted via ``knowledge``). This surfaces scope creep.

    Every check must pass for ``passed=True`` -- no partial credit (see the
    Scoring section of the contract schema). ``score`` is the pass ratio,
    kept only as diagnostic detail.
    """

    name = "input_context"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        span_index = self._build_span_index(snapshot)

        violations: list[Violation] = []
        entry_reports: dict[str, dict] = {}
        all_expected_paths: list[str] = []

        for entry in contract.input_context:
            path, ref_qualifiers = contract.resources.resolve(entry.resource)
            all_expected_paths.append(path)
            terms = list(entry.terms) + list(ref_qualifiers)

            retrieved, missing_paths, closest_match = self._check_paths([path], span_index)
            found_terms, missing_terms, term_locations = self._check_terms(terms, span_index)

            reasons: list[str] = []
            if missing_paths:
                hint = f" (closest tool read was: '{closest_match}')" if closest_match else " (no file reads observed at all)"
                reasons.append(f"expected file never retrieved by any tool: {path}{hint}")
                violations.append(
                    Violation(
                        code="context_path_not_retrieved",
                        message=(
                            f"Resource '{entry.resource}' expected to be read for context, "
                            f"but no tool call ever referenced it{hint}"
                        ),
                        plugin=self.name,
                        resource=entry.resource,
                        evidence={"path": path, "closest_match": closest_match},
                    )
                )
            if missing_terms:
                reasons.append(f"term(s) never observed in any tool call's input or output: {missing_terms}")
                violations.append(
                    Violation(
                        code="context_deviation",
                        message=(
                            f"Resource '{entry.resource}' declares terms {terms}, "
                            f"but {missing_terms} never showed up in any tool call's input or "
                            f"output — the agent's actual context appears to have drifted from "
                            f"what the task expected"
                        ),
                        plugin=self.name,
                        resource=entry.resource,
                        evidence={"terms": terms, "missing_terms": missing_terms, "term_locations": term_locations},
                    )
                )

            entry_reports[entry.resource] = {
                "path": path,
                "retrieved": bool(retrieved),
                "terms": terms,
                "found_terms": found_terms,
                "missing_terms": missing_terms,
                "term_locations": term_locations,
                "passed": not missing_paths and not missing_terms,
                "reason": "; ".join(reasons) if reasons else "context fully grounded",
            }

        # Qualifier terms parsed from `output[]` references -- output itself has no
        # content-relevance check, so this plugin checks them instead.
        output_qualifier_terms: list[str] = []
        for write in contract.output:
            path, ref_qualifiers = contract.resources.resolve(write.resource)
            all_expected_paths.append(path)
            output_qualifier_terms.extend(ref_qualifiers)

        output_found, output_missing, output_locations = self._check_terms(output_qualifier_terms, span_index)

        knowledge_patterns = list(contract.knowledge)
        unrelated_reads = self._find_unrelated_reads(all_expected_paths + knowledge_patterns, span_index)

        unrelated_label = "unrelated reads"
        if unrelated_reads:
            unrelated_detail = f"scope creep -- read but not declared for any resource: {unrelated_reads}"
            violations.append(
                Violation(
                    code="unrelated_context_fetched",
                    message=f"File(s) read that aren't declared as context/target for any resource: {unrelated_reads}",
                    plugin=self.name,
                    resource=unrelated_label,
                    evidence={
                        "unrelated_paths": unrelated_reads,
                        "expected_paths": sorted(set(all_expected_paths)),
                        "knowledge": sorted(set(knowledge_patterns)),
                    },
                )
            )
        else:
            unrelated_detail = "no unrelated files read"

        # Standard "checks" contract (see PluginResult docs / Scoring section):
        # one entry per named thing this plugin evaluated. Every entry must
        # pass for `passed=True` -- no hard/soft split.
        checks: dict[str, dict] = {
            resource: {"passed": r["passed"], "detail": r["reason"]}
            for resource, r in entry_reports.items()
        }
        output_qualifiers_label = "output qualifiers"
        if output_qualifier_terms:
            checks[output_qualifiers_label] = {
                "passed": not output_missing,
                "detail": (
                    f"missing: {output_missing}" if output_missing else "all output-declared qualifiers observed"
                ),
            }
        checks[unrelated_label] = {"passed": not unrelated_reads, "detail": unrelated_detail}

        passed, score = score_from_checks(checks)

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=score,
            violations=violations,
            evidence={
                "entries": entry_reports,
                "output_qualifier_terms": output_qualifier_terms,
                "output_qualifiers_found": output_found,
                "output_qualifiers_missing": output_missing,
                "unrelated_reads": unrelated_reads,
                "checks": checks,
            },
        )

    def _find_unrelated_reads(self, expected_patterns: list[str], span_index: list[SpanIndexEntry]) -> list[str]:
        """Files pulled into context via read_files that match no declared resource/knowledge path."""
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
            expected for expected in expected_paths if any(_paths_match(expected, seen) for seen in all_seen_paths)
        }
        missing = [p for p in expected_paths if p not in retrieved]

        closest_match = None
        if missing and all_seen_paths:
            best_ratio = 0.0
            for expected in missing:
                for seen in all_seen_paths:
                    ratio = difflib.SequenceMatcher(None, expected.lstrip("/"), seen.lstrip("/")).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        closest_match = seen
        return retrieved, missing, closest_match

    def _check_terms(
        self, terms: list[str], span_index: list[SpanIndexEntry]
    ) -> tuple[list[str], list[str], dict[str, str]]:
        """A term counts as grounded if it shows up in a tool call's input
        *or* its output -- either is legitimate evidence the agent actually
        engaged with it. ``locations`` records which side(s) each found term
        came from.
        """
        found: list[str] = []
        missing: list[str] = []
        locations: dict[str, str] = {}
        for term in terms:
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
