from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation, score_from_checks
from wm_agents_validator.models.trace_snapshot import DELEGATION_TOOL_NAMES, SKILL_TOOL, TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract
from wm_agents_validator.plugins.timing import fmt_ms, sum_duration_ms

# Framework/orchestration mechanics, not domain tool calls -- skill loading is
# already checked by SkillsLoadedPlugin, and delegation calls have no
# domain-tool identity of their own. No existing contract declares these in
# `tools:`, so they're excluded from the "unrelated tools" check entirely
# rather than requiring every contract to enumerate them.
_STRUCTURAL_TOOLS = DELEGATION_TOOL_NAMES | {SKILL_TOOL}


class ToolCallsPlugin:
    """Checks the contract-wide ``tools`` policy: every ``required`` tool was
    used somewhere in the trace, and no ``forbidden`` tool was used anywhere.

    ``tools`` is one flat, global policy (not addressed to any resource) --
    neither real contract in this repo ever needed a different tool policy
    per resource, so there's no per-resource scoping here.

    ``snapshot.tool_names`` already accounts for tools invoked indirectly via
    ``execute_tool`` (wm-agent-server's generic dispatcher) -- the wrapped
    tool's own name is surfaced alongside ``"execute_tool"`` itself during
    normalization (see ``_build_tools_summary`` in ``trace/normalizer.py``),
    so a required/forbidden MCP tool reached only through ``execute_tool``
    is still checked by its real name here, not missed. The same unwrapping
    is what makes the "unrelated tools" check below meaningful for
    ``execute_tool``-dispatched calls too: a ``tool_name`` invoked that way
    but never declared in ``required``/``optional``/``forbidden`` shows up
    by its real name, not hidden behind the generic wrapper.

    It also checks the inverse direction: any tool actually called that
    isn't declared anywhere in the policy (``required``, ``optional``, or
    ``forbidden``) is surfaced as an "unrelated tool" -- an undeclared tool
    is neither vetted as expected nor explicitly banned, so its use is
    unaccounted-for agent behavior. This only fails the plugin when the
    contract's tool policy is non-empty (i.e. it actually declared some
    opinion about which tools to use); with the policy fully empty, called
    tools are reported informationally only -- the same "scope declared"
    pattern used by ``InputContextPlugin``/``OutputPlugin``'s
    unrelated-reads/unrelated-changes checks. Skill-loading and delegation
    calls (``_STRUCTURAL_TOOLS``) are excluded entirely -- they're framework
    mechanics with their own dedicated checks elsewhere, not part of any
    contract's domain tool policy.
    """

    name = "tool_calls"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        violations: list[Violation] = []
        checks: dict[str, dict] = {}
        policy = contract.tools

        for required_tool in policy.required:
            used = required_tool in snapshot.tool_names
            checks[required_tool] = {
                "passed": used,
                "detail": "used" if used else "required tool never used",
            }
            if not used:
                violations.append(
                    Violation(
                        code="required_tool_missing",
                        message=f"Required tool '{required_tool}' never used",
                        plugin=self.name,
                        evidence={"required": policy.required, "actual_tools": snapshot.tool_names},
                    )
                )

        forbidden_used = [tool for tool in policy.forbidden if tool in snapshot.tool_names]
        forbidden_label = "forbidden tools"
        if forbidden_used:
            checks[forbidden_label] = {"passed": False, "detail": f"forbidden tool(s) used: {forbidden_used}"}
            violations.append(
                Violation(
                    code="forbidden_tool_used",
                    message=f"Forbidden tool(s) used: {forbidden_used}",
                    plugin=self.name,
                    evidence={"forbidden": policy.forbidden, "actual_tools": snapshot.tool_names},
                )
            )
        else:
            checks[forbidden_label] = {"passed": True, "detail": "no forbidden tool used"}

        declared_tools = set(policy.required) | set(policy.optional) | set(policy.forbidden)
        unrelated_tools = [
            tool
            for tool in snapshot.tool_names
            if tool not in declared_tools and tool not in _STRUCTURAL_TOOLS
        ]
        scope_declared = bool(policy.required or policy.optional or policy.forbidden)

        unrelated_label = "unrelated tools"
        if not scope_declared:
            checks[unrelated_label] = {
                "passed": True,
                "detail": (
                    f"not enforced -- tools.required/optional/forbidden are all empty, so there's no "
                    f"declared policy to violate ({len(unrelated_tools)} tool(s) observed): {unrelated_tools}"
                    if unrelated_tools
                    else "no unrelated tools called"
                ),
            }
        elif unrelated_tools:
            checks[unrelated_label] = {
                "passed": False,
                "detail": f"tool(s) called but not declared in tools policy: {unrelated_tools}",
            }
            violations.append(
                Violation(
                    code="unrelated_tool_called",
                    message=f"Tool(s) called that aren't declared as required/optional/forbidden: {unrelated_tools}",
                    plugin=self.name,
                    evidence={"unrelated_tools": unrelated_tools, "declared_tools": sorted(declared_tools)},
                )
            )
        else:
            checks[unrelated_label] = {"passed": True, "detail": "no unrelated tools called"}

        passed, score = score_from_checks(checks)

        # Informational only -- added after scoring so it never affects
        # passed/score; see plugins/timing.py.
        tool_spans = [span for span in snapshot.spans if span.type == "TOOL"]
        tool_calls_ms = sum_duration_ms(tool_spans)
        checks["tool call time"] = {
            "passed": True,
            "detail": f"{fmt_ms(tool_calls_ms)} across {len(tool_spans)} call(s)",
        }

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=score,
            violations=violations,
            evidence={
                "checks": checks,
                "unrelated_tools": unrelated_tools,
                "declared_tools": sorted(declared_tools),
            },
        )
