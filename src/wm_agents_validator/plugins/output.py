from __future__ import annotations

from wm_agents_validator.contracts.expressions import glob_match
from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation, score_from_checks
from wm_agents_validator.models.trace_snapshot import (
    TraceSnapshot,
    _paths_match,
    _span_base_name,
    extract_paths_from_input,
    match_satisfied,
    matching_tool_calls,
    unwrap_execute_tool,
)
from wm_agents_validator.models.workflow_contract import (
    ExactMatchClause,
    SubstringMatchClause,
    ToolCheck,
    WorkflowContract,
)
from wm_agents_validator.plugins.timing import fmt_ms, is_output_generation_tool, sum_duration_ms

_OPERATION_TO_FILE_CHANGE_OPS: dict[str, set[str]] = {
    "CREATE": {"write", "edit"},
    "UPDATE": {"write", "edit"},
    "DELETE": {"delete"},
}


def _tool_check_path_patterns(tool_checks: list[ToolCheck]) -> list[str]:
    """Literal string values out of every ``ToolCheck.match`` clause, treated
    as additional "allowed" path patterns for the unrelated-changes check --
    a contract that already asserts ``tool: edit_file_content`` /
    ``match: [".../Login.js"]`` has, by writing that literal path, declared
    it as an expected change target; it shouldn't also be flagged as an
    undeclared/unrelated write. Only ``SubstringMatchClause``/
    ``ExactMatchClause`` values are usable this way (each is a literal
    string) -- a ``RegexMatchClause`` pattern isn't a literal path, so it's
    skipped. A non-path value (e.g. a locale code, a page name) is harmless
    here: the unrelated-changes check only matches it against an
    actually-changed path via exact/glob comparison, so it can't
    accidentally whitelist something unrelated. Mirrors
    ``InputContextPlugin._tool_check_path_patterns``.
    """
    patterns: list[str] = []
    for check in tool_checks:
        for clause in check.match:
            if isinstance(clause, SubstringMatchClause):
                patterns.extend(clause.values)
            elif isinstance(clause, ExactMatchClause):
                patterns.extend(str(v) for v in clause.fields.values())
    return patterns


class OutputPlugin:
    """Checks whether each ``output[]`` entry's resolved resource was actually
    created/updated/deleted as declared, and that nothing outside the declared
    ``output`` scope changed.

    ``output`` is the exhaustive scope of what's allowed to change -- a
    resource that's only ever referenced under ``input_context`` (never
    ``output``) is automatically protected, since any change to it is caught
    by the unrelated-diff check below. A ``ToolCheck``'s own ``match:``
    literal values also count as declared/allowed for this check (see
    ``_tool_check_path_patterns``) -- a change already asserted via
    ``tool: edit_file_content`` / ``match: [...]`` shouldn't also be flagged
    as unrelated.

    A ``WriteSpec.match`` clause (only checked when non-empty) additionally
    requires that the *same* write-tool call whose input matched the resolved
    resource path also satisfy the declared key=value (or value-only)
    assertions -- see ``match_satisfied``. This is what makes a name-less,
    policy-constrained ``resource`` reference (e.g. ``page.PetTable.variable``)
    meaningful rather than a near no-op: it verifies which properties the
    created/updated resource actually has, independent of what it was named.
    Path-based evidencing spans are any tool call classified as
    output-generating by ``is_output_generation_tool`` (see
    ``plugins/timing.py``) -- everything that isn't pure input-gathering, a
    skill load, or a delegation, checked after unwrapping ``execute_tool`` to
    whatever it actually invoked.

    A ``ToolCheck`` entry (``tool:`` + optional ``match:``, see
    ``models/workflow_contract.py``) is a completely separate, independent
    kind of ``output[]`` entry -- not tied to any ``resource:``/path at all.
    It passes when a matching call is found anywhere in the trace (resolved
    generically -- see ``resolve_dotted_tool_calls`` -- with zero built-in
    knowledge of any specific tool's name), and fails otherwise. It proves
    nothing about a resource's create/update/delete state; it's its own
    pass/fail check, for a tool whose args carry no file path the framework
    could compare against ``resources``' registered path.

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
        tool_checks = [entry for entry in contract.output if isinstance(entry, ToolCheck)]

        for entry in contract.output:
            if isinstance(entry, ToolCheck):
                calls = matching_tool_calls(snapshot.spans, [entry])
                label = f"tool:{entry.tool}"
                if calls:
                    checks[label] = {"passed": True, "detail": f"matching call to {entry.tool} observed"}
                else:
                    detail = f"no call to {entry.tool} matching {entry.match} found anywhere in the trace" if entry.match else f"no call to {entry.tool} found anywhere in the trace"
                    checks[label] = {"passed": False, "detail": detail}
                    violations.append(
                        Violation(
                            code="tool_check_not_found",
                            message=f"Tool check '{entry.tool}': {detail}",
                            plugin=self.name,
                            resource=label,
                            evidence={"tool": entry.tool, "match": entry.match},
                        )
                    )
                continue

            write = entry
            path, _qualifiers = contract.resources.resolve(write.resource)
            allowed_patterns.append(path)

            matching_ops = {fc.operation for fc in snapshot.file_changes if glob_match(path, fc.path) or fc.path == path}
            expected_ops = _OPERATION_TO_FILE_CHANGE_OPS[write.operation]
            operation_ok = bool(matching_ops & expected_ops)

            match_ok = True
            evidencing_names: list[str] = []
            if write.match:  # falsy for both {} and [] -- no special-casing needed
                evidencing_calls: list[tuple[str, dict]] = []
                for span in snapshot.spans:
                    if span.type != "TOOL":
                        continue
                    name, tool_input = unwrap_execute_tool(_span_base_name(span.name), span.input or {})
                    if not is_output_generation_tool(name):
                        continue
                    if any(_paths_match(path, p) for p in extract_paths_from_input(tool_input, name)):
                        evidencing_calls.append((name, tool_input))
                match_ok = any(match_satisfied(write.match, tool_input) for _, tool_input in evidencing_calls)
                evidencing_names = [name for name, _ in evidencing_calls]

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

        allowed_patterns_with_tool_checks = allowed_patterns + _tool_check_path_patterns(tool_checks)
        unrelated = [
            path
            for path in changed_paths
            if not any(glob_match(p, path) or path == p for p in allowed_patterns_with_tool_checks)
        ]

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
                    evidence={"unrelated_paths": unrelated, "allowed_patterns": allowed_patterns_with_tool_checks},
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
            if span.type == "TOOL"
            and is_output_generation_tool(unwrap_execute_tool(_span_base_name(span.name), span.input or {})[0])
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
                "allowed_patterns": allowed_patterns_with_tool_checks,
                "checks": checks,
            },
        )
