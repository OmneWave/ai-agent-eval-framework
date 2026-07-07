from __future__ import annotations

from wm_agents_validator.models.plugin_result import EvalContext, PluginResult, Violation
from wm_agents_validator.models.trace_snapshot import TraceSnapshot
from wm_agents_validator.models.workflow_contract import WorkflowContract


class IntentVerificationPlugin:
    name = "intent_verification"

    def evaluate(
        self,
        snapshot: TraceSnapshot,
        contract: WorkflowContract,
        context: EvalContext | None = None,
    ) -> PluginResult:
        expected = contract.intent.expected_skill
        expected_skills = [expected] if isinstance(expected, str) else list(expected)
        allowed_skills = list(contract.intent.allowed_skills)

        loaded_skills: list[str] = []
        for load in snapshot.skill_loads:
            loaded_skills.extend(load.skill_names)

        unique_loaded = list(dict.fromkeys(loaded_skills))
        # allowed_skills are optional: the LLM may or may not load them, and
        # doing either is fine, so they never count as "extra" and are never
        # required for the score below.
        optional_skills_loaded = [s for s in unique_loaded if s in allowed_skills]
        extra_skills = [
            s for s in unique_loaded if s not in expected_skills and s not in allowed_skills
        ]

        successful = [s for load in snapshot.skill_loads if load.success for s in load.skill_names]
        missing = [s for s in expected_skills if s not in successful]
        never_loaded = [s for s in missing if s not in loaded_skills]
        failed_to_load = [s for s in missing if s in loaded_skills and s not in successful]
        correct = len(expected_skills) - len(missing)
        denominator = len(expected_skills) + len(extra_skills)
        score = correct / denominator if denominator else 0.0

        evidence = {
            "expected_skill": expected,
            "allowed_skills": allowed_skills,
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
                    message=f"Expected skill(s) never loaded: {never_loaded}",
                    plugin=self.name,
                    evidence=evidence,
                )
            )
        if failed_to_load:
            violations.append(
                Violation(
                    code="skill_load_failed",
                    message=f"Expected skill(s) requested but load failed: {failed_to_load}",
                    plugin=self.name,
                    evidence=evidence,
                )
            )
        if extra_skills:
            violations.append(
                Violation(
                    code="extra_skill_loaded",
                    message=f"Extra skill(s) loaded beyond expected: {extra_skills}",
                    plugin=self.name,
                    resource="extra skills",
                    evidence=evidence,
                )
            )

        # One check per expected skill (loaded/failed/never-loaded), plus one
        # rollup for scope creep -- so a partial pass/fail always shows *which*
        # skill(s) are responsible, not just an aggregate score.
        checks: dict[str, dict] = {}
        for skill in expected_skills:
            if skill in successful:
                checks[skill] = {"passed": True, "detail": "loaded successfully"}
            elif skill in loaded_skills:
                checks[skill] = {"passed": False, "detail": "requested but load failed"}
            else:
                checks[skill] = {"passed": False, "detail": "expected skill never loaded"}
        checks["extra skills"] = {
            "passed": not extra_skills,
            "detail": (
                f"unexpected skill(s) loaded: {extra_skills}"
                if extra_skills
                else "none beyond expected/allowed"
            ),
        }
        evidence["checks"] = checks

        return PluginResult(
            plugin=self.name,
            passed=not missing,
            score=score,
            violations=violations,
            evidence=evidence,
        )
