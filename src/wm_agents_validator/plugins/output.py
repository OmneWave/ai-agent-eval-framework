from __future__ import annotations

from wm_agents_validator.contracts.expressions import glob_match
from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation, score_from_checks
from wm_agents_validator.models.trace_snapshot import (
    TraceSnapshot,
    _paths_match,
    _span_base_name,
    extract_paths_from_input,
)
from wm_agents_validator.models.workflow_contract import WorkflowContract
from wm_agents_validator.plugins.timing import OUTPUT_GENERATION_TOOLS, fmt_ms, sum_duration_ms

_OPERATION_TO_FILE_CHANGE_OPS: dict[str, set[str]] = {
    "CREATE": {"write", "edit"},
    "UPDATE": {"write", "edit"},
    "DELETE": {"delete"},
}


def _match_satisfied(match: dict | list, span_input: dict) -> bool:
    """Checks a ``WriteSpec.match`` clause against one evidencing *write*-tool
    call's structured input only -- ``match`` verifies what a write call
    actually did, which is a distinct question from whether the right content
    was *read* (that's ``terms``/``input_context.py``'s job, checked against
    read-tool calls' input and output there). Keeping the two cleanly split by
    tool category, not blended, is deliberate.

    - dict form: every key must exist literally in ``span_input``, value exact
      match (case-insensitive) -- for tools with flat, known-field-name kwargs
      (e.g. ``ui_createApiAwareVariable``'s ``operationId``).
    - list form: every value must appear as a *substring* of some value in
      ``span_input`` (case-insensitive) -- substring, not exact-equality,
      deliberately: a short keyword can never equal a whole field's value
      (e.g. a widget tag inside ``write_file``'s ``file_content``), only
      appear within it.
    """
    if isinstance(match, dict):
        return all(str(span_input.get(k, "")).lower() == str(v).lower() for k, v in match.items())
    existing_values = [str(v).lower() for v in span_input.values()]
    return all(any(str(v).lower() in existing for existing in existing_values) for v in match)


class OutputPlugin:
    """Checks whether each ``output[]`` entry's resolved resource was actually
    created/updated/deleted as declared, and that nothing outside the declared
    ``output`` scope changed.

    ``output`` is the exhaustive scope of what's allowed to change -- a
    resource that's only ever referenced under ``input_context`` (never
    ``output``) is automatically protected, since any change to it is caught
    by the unrelated-diff check below.

    A ``WriteSpec.match`` clause (only checked when non-empty) additionally
    requires that the *same* write-tool call whose input matched the resolved
    resource path also satisfy the declared key=value (or value-only)
    assertions -- see ``_match_satisfied``. This is what makes a name-less,
    policy-constrained ``resource`` reference (e.g. ``page.PetTable.variable``)
    meaningful rather than a near no-op: it verifies which properties the
    created/updated resource actually has, independent of what it was named.
    Evidencing spans are restricted to ``OUTPUT_GENERATION_TOOLS`` -- ``match``
    is about what a *write* call did, not about verifying read content (that's
    ``terms``/``input_context.py``'s job, checked separately against read-tool
    calls).

    Every check must pass for ``passed=True`` -- no partial credit (see the
    Scoring section of the contract schema).
    """

    name = "output"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        violations: list[Violation] = []
        checks: dict[str, dict] = {}
        changed_paths = {fc.path for fc in snapshot.file_changes}
        allowed_patterns: list[str] = []

        for write in contract.output:
            path, _qualifiers = contract.resources.resolve(write.resource)
            allowed_patterns.append(path)

            matching_ops = {fc.operation for fc in snapshot.file_changes if glob_match(path, fc.path) or fc.path == path}
            expected_ops = _OPERATION_TO_FILE_CHANGE_OPS[write.operation]
            operation_ok = bool(matching_ops & expected_ops)

            match_ok = True
            evidencing_names: list[str] = []
            if write.match:  # falsy for both {} and [] -- no special-casing needed
                evidencing_spans = [
                    span
                    for span in snapshot.spans
                    if span.type == "TOOL"
                    and _span_base_name(span.name) in OUTPUT_GENERATION_TOOLS
                    and any(
                        _paths_match(path, p)
                        for p in extract_paths_from_input(span.input or {}, _span_base_name(span.name))
                    )
                ]
                match_ok = any(_match_satisfied(write.match, span.input or {}) for span in evidencing_spans)
                evidencing_names = [_span_base_name(s.name) for s in evidencing_spans]

            passed_entry = operation_ok and match_ok
            if passed_entry:
                checks[write.resource] = {"passed": True, "detail": f"{write.operation} observed on {path}"}
            else:
                # Report the ACTUAL failure, not a fixed template -- when the
                # operation itself was observed fine and only `match` failed,
                # leading with "expected CREATE... observed: ['write']" reads
                # as an operation mismatch that never happened.
                if not operation_ok:
                    detail = f"expected {write.operation} on {path}, observed operations: {sorted(matching_ops) or 'none'}"
                    code = "output_operation_mismatch"
                else:
                    detail = f"{write.operation} observed on {path}, but match clause {write.match} not satisfied by any evidencing call ({evidencing_names})"
                    code = "output_match_mismatch"
                checks[write.resource] = {"passed": False, "detail": detail}
                violations.append(
                    Violation(
                        code=code,
                        message=f"Resource '{write.resource}': {detail}",
                        plugin=self.name,
                        resource=write.resource,
                        evidence={
                            "path": path,
                            "expected_operation": write.operation,
                            "observed_operations": sorted(matching_ops),
                            "match": write.match,
                            "match_satisfied": match_ok,
                        },
                    )
                )

        unrelated = [path for path in changed_paths if not any(glob_match(p, path) or path == p for p in allowed_patterns)]

        unrelated_label = "unrelated changes"
        if unrelated:
            checks[unrelated_label] = {
                "passed": False,
                "detail": f"file(s) changed outside contract scope: {sorted(unrelated)}",
            }
            violations.append(
                Violation(
                    code="unrelated_file_changed",
                    message=f"Files changed outside contract scope: {unrelated}",
                    plugin=self.name,
                    resource=unrelated_label,
                    evidence={"unrelated_paths": unrelated, "allowed_patterns": allowed_patterns},
                )
            )
        else:
            checks[unrelated_label] = {"passed": True, "detail": "no changes outside contract scope"}

        passed, score = score_from_checks(checks)

        # Informational only -- added after scoring so it never affects
        # passed/score; see plugins/timing.py.
        output_generation_spans = [
            span
            for span in snapshot.spans
            if span.type == "TOOL" and _span_base_name(span.name) in OUTPUT_GENERATION_TOOLS
        ]
        output_generation_ms = sum_duration_ms(output_generation_spans)
        checks["output generation time"] = {
            "passed": True,
            "detail": f"{fmt_ms(output_generation_ms)} across {len(output_generation_spans)} call(s)",
        }

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=score,
            violations=violations,
            evidence={
                "changed_paths": sorted(changed_paths),
                "allowed_patterns": allowed_patterns,
                "checks": checks,
            },
        )
