from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation, score_from_checks
from wm_agents_validator.models.trace_snapshot import SKILL_TOOL, TraceSnapshot, _span_base_name
from wm_agents_validator.models.workflow_contract import WorkflowContract
from wm_agents_validator.plugins.timing import fmt_ms, sum_duration_ms


def _first_success_index(snapshot: TraceSnapshot, skill_name: str) -> int | None:
    """Position (in ``snapshot.skill_loads``, index order) of the first
    record where ``skill_name`` loaded successfully, or ``None`` if it never
    did. List-index order, not raw ``timestamp`` comparison, is the ordering
    signal used throughout this plugin -- only the spans-derived half of
    ``skill_loads`` has reliable per-call chronological timestamps; the
    trace-message-derived half is appended afterward with coarser, duplicated
    timestamps, and the merge step does not re-sort by timestamp.
    """
    for i, load in enumerate(snapshot.skill_loads):
        if load.success and skill_name in load.skill_names:
            return i
    return None


class SkillsLoadedPlugin:
    name = "skills_loaded"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        required_skills = [r.name for r in contract.skills.required]
        optional_skills = list(contract.skills.optional)

        loaded_skills: list[str] = []
        for load in snapshot.skill_loads:
            loaded_skills.extend(load.skill_names)

        unique_loaded = list(dict.fromkeys(loaded_skills))
        # optional_skills are optional: the LLM may or may not load them, and
        # doing either is fine, so they never count as "extra".
        optional_skills_loaded = [s for s in unique_loaded if s in optional_skills]
        extra_skills = [
            s for s in unique_loaded if s not in required_skills and s not in optional_skills
        ]

        successful = [s for load in snapshot.skill_loads if load.success for s in load.skill_names]
        missing = [s for s in required_skills if s not in successful]
        never_loaded = [s for s in missing if s not in loaded_skills]
        failed_to_load = [s for s in missing if s in loaded_skills and s not in successful]

        evidence = {
            "required": required_skills,
            "optional": optional_skills,
            "loaded_skills": loaded_skills,
            "skill_load_count": len(snapshot.skill_loads),
            "optional_skills_loaded": optional_skills_loaded,
            "extra_skills_loaded": extra_skills,
        }

        violations: list[Violation] = []
        if never_loaded:
            violations.append(
                Violation(
                    code="skill_not_loaded",
                    message=f"Required skill(s) never loaded: {never_loaded}",
                    plugin=self.name,
                    evidence=evidence,
                )
            )
        if failed_to_load:
            violations.append(
                Violation(
                    code="skill_load_failed",
                    message=f"Required skill(s) requested but load failed: {failed_to_load}",
                    plugin=self.name,
                    evidence=evidence,
                )
            )
        if extra_skills:
            violations.append(
                Violation(
                    code="extra_skill_loaded",
                    message=f"Extra skill(s) loaded beyond required/optional: {extra_skills}",
                    plugin=self.name,
                    resource="extra skills",
                    evidence=evidence,
                )
            )

        # One check per required skill (loaded/failed/never-loaded), plus one
        # rollup for scope creep -- every check must pass for `passed=True`
        # (see Scoring section: no partial credit).
        checks: dict[str, dict] = {}
        for skill in required_skills:
            if skill in successful:
                checks[skill] = {"passed": True, "detail": "loaded successfully"}
            elif skill in loaded_skills:
                checks[skill] = {"passed": False, "detail": "requested but load failed"}
            else:
                checks[skill] = {"passed": False, "detail": "required skill never loaded"}

        # Dependency-order edges: for every `depends_on` declared on a required
        # skill, verify the trace actually loaded the dependency at or before
        # the dependent -- see docs/CONTRACT_SPEC.md's "Skills" section for the
        # full four-case rationale. An edge is a claim about relative order
        # between two things that BOTH happened, so the two "never loaded"
        # cases are NOT symmetric: if the dependent itself never loaded, there
        # is no order to have violated (that failure already belongs to the
        # checks/violations above), whereas the dependent loading despite its
        # dependency never having loaded is the one real failure this feature
        # exists to catch.
        edge_results: list[dict] = []
        order_violated_edges: list[str] = []
        for requirement in contract.skills.required:
            for dep in requirement.depends_on:
                dep_idx = _first_success_index(snapshot, dep)
                name_idx = _first_success_index(snapshot, requirement.name)
                label = f"{requirement.name} after {dep}"

                if dep_idx is None and name_idx is None:
                    verdict, passed, detail = (
                        "vacuous_dependent_never_loaded",
                        True,
                        f"not applicable -- '{requirement.name}' never loaded, so there is no "
                        f"order to violate (see the '{requirement.name}' required-skill check)",
                    )
                elif dep_idx is None:  # name_idx is not None here
                    verdict, passed, detail = (
                        "violated_dependency_missing",
                        False,
                        f"'{requirement.name}' loaded but dependency '{dep}' was never loaded successfully",
                    )
                elif name_idx is None:
                    verdict, passed, detail = (
                        "vacuous_dependent_never_loaded",
                        True,
                        f"not applicable -- '{requirement.name}' never loaded, so there is no "
                        f"order to violate (see the '{requirement.name}' required-skill check)",
                    )
                elif dep_idx > name_idx:
                    verdict, passed, detail = (
                        "violated_order",
                        False,
                        f"'{requirement.name}' loaded at position {name_idx} before '{dep}' "
                        f"(first successful at position {dep_idx})",
                    )
                else:
                    verdict, passed, detail = (
                        "satisfied",
                        True,
                        f"loaded at position {name_idx}, after '{dep}' (first successful at position {dep_idx})",
                    )

                checks[label] = {"passed": passed, "detail": detail}
                if verdict in ("violated_order", "violated_dependency_missing"):
                    order_violated_edges.append(label)
                edge_results.append(
                    {
                        "from": dep,
                        "to": requirement.name,
                        "verdict": verdict,
                        "from_position": dep_idx,
                        "to_position": name_idx,
                        "detail": detail,
                    }
                )

        if order_violated_edges:
            violations.append(
                Violation(
                    code="skill_dependency_order_violated",
                    message=f"Skill dependency order violated: {order_violated_edges}",
                    plugin=self.name,
                    resource="skill dependency order",
                    evidence=evidence,
                )
            )

        checks["extra skills"] = {
            "passed": not extra_skills,
            "detail": (
                f"unexpected skill(s) loaded: {extra_skills}"
                if extra_skills
                else "none beyond required/optional"
            ),
        }
        evidence["checks"] = checks

        # Structured DAG data for UI visualization (expected graph vs. actual
        # load sequence, and where they diverge) -- data only, no rendering
        # here. `edge_results` reuses the exact dep_idx/name_idx/verdict
        # values computed above, so it can never disagree with `checks`.
        first_success_position: dict[str, int] = {}
        for i, load in enumerate(snapshot.skill_loads):
            if load.success:
                for name in load.skill_names:
                    first_success_position.setdefault(name, i)
        evidence["skill_dag"] = {
            "expected": {
                "nodes": required_skills,
                "edges": [
                    {"from": dep, "to": r.name}
                    for r in contract.skills.required
                    for dep in r.depends_on
                ],
            },
            "actual": {
                "events": [
                    {
                        "position": i,
                        "skill_names": load.skill_names,
                        "success": load.success,
                        "timestamp": load.timestamp,
                    }
                    for i, load in enumerate(snapshot.skill_loads)
                ],
                "first_success_position": first_success_position,
            },
            "edge_results": edge_results,
        }

        passed, score = score_from_checks(checks)

        # Informational only -- added after scoring so it never affects
        # passed/score; see plugins/timing.py.
        skill_load_spans = [
            span for span in snapshot.spans if span.type == "TOOL" and _span_base_name(span.name) == SKILL_TOOL
        ]
        skill_load_ms = sum_duration_ms(skill_load_spans)
        checks["skill load time"] = {
            "passed": True,
            "detail": f"{fmt_ms(skill_load_ms)} across {len(skill_load_spans)} call(s)",
        }

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=score,
            violations=violations,
            evidence=evidence,
        )
