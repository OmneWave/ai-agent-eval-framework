import pytest

from wm_agents_validator.plugins.skills_loaded import SkillsLoadedPlugin


def test_skills_loaded_passes(snapshot, contract):
    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0


def test_skills_loaded_reports_skill_load_time_without_affecting_score(snapshot, contract):
    # Informational only -- added after scoring, so it must never turn a
    # would-be-clean pass into a partial score.
    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    time_check = result.evidence["checks"]["skill load time"]
    assert time_check["passed"] is True
    assert "call(s)" in time_check["detail"]


def test_skills_loaded_fails_wrong_skill(snapshot, contract):
    required_count = len(contract.skills.required)
    snapshot.skill_loads[0].skill_names = ["wrong_skill"]
    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "skill_not_loaded" in codes
    assert "extra_skill_loaded" in codes
    assert "wrong_skill" in result.evidence["extra_skills_loaded"]
    assert result.score == pytest.approx((required_count - 1) / (required_count + 1))


def test_skills_loaded_fails_all_skills_missing(snapshot, contract):
    snapshot.skill_loads = []
    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert not result.passed
    # Every required-skill check fails; the "extra skills" rollup still
    # passes trivially (nothing was loaded at all), so score is its ratio.
    assert result.score == pytest.approx(1 / (len(contract.skills.required) + 1))
    assert result.violations[0].code == "skill_not_loaded"


def test_skills_loaded_flags_extra_skill_and_fails(snapshot, contract):
    # Under the SWE-bench-style scoring rule, an extra skill loaded beyond
    # required/optional now fails the plugin too -- no partial credit.
    snapshot.skill_loads.append(
        snapshot.skill_loads[0].model_copy(update={"skill_names": ["extra-unexpected-skill"]})
    )
    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert not result.passed
    assert result.score < 1.0
    assert "extra-unexpected-skill" in result.evidence["extra_skills_loaded"]
    codes = [v.code for v in result.violations]
    assert codes == ["extra_skill_loaded"]


def _with_explore_codebase_optional(contract):
    # The shared fixture contract currently declares no optional skills at all
    # (skills.optional == []) -- explore-codebase/explore-api were moved to
    # required at some point. Derive a local variant with explore-codebase
    # moved back to optional so "optional skill" behavior still has something
    # real to exercise, without mutating the shared contract fixture.
    required = [s for s in contract.skills.required if s != "explore-codebase"]
    return contract.model_copy(
        update={
            "skills": contract.skills.model_copy(
                update={"required": required, "optional": ["explore-codebase"]}
            )
        }
    )


def test_skills_loaded_treats_loaded_optional_skill_as_optional(snapshot, contract):
    # Fixture already loads "explore-codebase"; as an optional skill, loading
    # it must not count as "extra" or fail the plugin.
    contract = _with_explore_codebase_optional(contract)
    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.evidence["optional_skills_loaded"] == ["explore-codebase"]
    assert result.evidence["extra_skills_loaded"] == []
    assert result.violations == []


def test_skills_loaded_does_not_require_optional_skill(snapshot, contract):
    # Dropping an optional skill load must not be treated as "missing".
    contract = _with_explore_codebase_optional(contract)
    snapshot.skill_loads = [
        load for load in snapshot.skill_loads if load.skill_names != ["explore-codebase"]
    ]
    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
