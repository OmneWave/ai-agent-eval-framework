from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation, score_from_checks
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


class SkillsLoadedPlugin:
    name = "skills_loaded"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        required = contract.skills.required
        required_skills = [required] if isinstance(required, str) else list(required)
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
            "required": required,
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
        checks["extra skills"] = {
            "passed": not extra_skills,
            "detail": (
                f"unexpected skill(s) loaded: {extra_skills}"
                if extra_skills
                else "none beyond required/optional"
            ),
        }
        evidence["checks"] = checks

        passed, score = score_from_checks(checks)

        return PluginResult(
            plugin=self.name,
            passed=passed,
            score=score,
            violations=violations,
            evidence=evidence,
        )
