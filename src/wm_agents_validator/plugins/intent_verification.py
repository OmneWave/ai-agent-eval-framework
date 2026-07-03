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
        loaded_skills: list[str] = []
        for load in snapshot.skill_loads:
            loaded_skills.extend(load.skill_names)

        evidence = {
            "expected_skill": expected,
            "loaded_skills": loaded_skills,
            "skill_load_count": len(snapshot.skill_loads),
        }

        successful = [s for load in snapshot.skill_loads if load.success for s in load.skill_names]
        if expected in successful:
            return PluginResult(
                plugin=self.name, passed=True, score=1.0, violations=[], evidence=evidence
            )

        violations: list[Violation] = []
        if not snapshot.skill_loads or not loaded_skills:
            violations.append(
                Violation(
                    code="skill_not_loaded",
                    message=f"Expected skill '{expected}' was never loaded",
                    plugin=self.name,
                    evidence=evidence,
                )
            )
            return PluginResult(
                plugin=self.name, passed=False, score=0.0, violations=violations, evidence=evidence
            )

        if expected in loaded_skills:
            violations.append(
                Violation(
                    code="skill_load_failed",
                    message=f"Skill '{expected}' was requested but load failed",
                    plugin=self.name,
                    evidence=evidence,
                )
            )
            return PluginResult(
                plugin=self.name, passed=False, score=0.0, violations=violations, evidence=evidence
            )

        violations.append(
            Violation(
                code="wrong_skill_loaded",
                message=f"Expected '{expected}' but loaded {loaded_skills}",
                plugin=self.name,
                evidence=evidence,
            )
        )
        return PluginResult(
            plugin=self.name, passed=False, score=0.5, violations=violations, evidence=evidence
        )
