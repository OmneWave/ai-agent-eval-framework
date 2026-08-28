import pytest

from wm_agents_validator.models.trace_snapshot import SkillLoadRecord
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
    required = [r for r in contract.skills.required if r.name != "explore-codebase"]
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


def _with_deps(contract, deps: dict[str, list[str]]):
    """Derive a contract variant where the named required skills get the
    given `depends_on` lists -- via `model_copy` (no re-validation), since
    these are always constructed from an already-valid fixture contract with
    real skill names, not exercising the load-time DAG validator (that lives
    in tests/test_models/test_workflow_contract.py instead)."""
    required = [
        r.model_copy(update={"depends_on": deps.get(r.name, [])})
        for r in contract.skills.required
    ]
    return contract.model_copy(
        update={"skills": contract.skills.model_copy(update={"required": required})}
    )


def test_skills_loaded_dag_passes_in_order(snapshot, contract):
    # Fixture snapshot already loads explore-codebase (index 1) before
    # explore-api (index 2) -- a real, already-satisfying order.
    contract = _with_deps(contract, {"explore-api": ["explore-codebase"]})
    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    check = result.evidence["checks"]["explore-api after explore-codebase"]
    assert check["passed"] is True
    assert result.violations == []


def test_skills_loaded_dag_order_violated(snapshot, contract):
    contract = _with_deps(contract, {"explore-api": ["explore-codebase"]})
    # Swap the two records so explore-api now loads before explore-codebase.
    loads = snapshot.skill_loads
    codebase_i = next(i for i, l in enumerate(loads) if l.skill_names == ["explore-codebase"])
    api_i = next(i for i, l in enumerate(loads) if l.skill_names == ["explore-api"])
    loads[codebase_i], loads[api_i] = loads[api_i], loads[codebase_i]

    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert not result.passed
    check = result.evidence["checks"]["explore-api after explore-codebase"]
    assert check["passed"] is False
    edge = next(
        e for e in result.evidence["skill_dag"]["edge_results"]
        if e["from"] == "explore-codebase" and e["to"] == "explore-api"
    )
    assert edge["verdict"] == "violated_order"
    codes = [v.code for v in result.violations]
    assert "skill_dependency_order_violated" in codes
    order_violation = next(v for v in result.violations if v.code == "skill_dependency_order_violated")
    assert "explore-api after explore-codebase" in order_violation.message


def test_skills_loaded_dag_dependency_missing(snapshot, contract):
    # dep ("explore-codebase") never loads at all, but the dependent
    # ("explore-api") does -- case 2: the one real failure this feature
    # exists to catch.
    contract = _with_deps(contract, {"explore-api": ["explore-codebase"]})
    snapshot.skill_loads = [
        load for load in snapshot.skill_loads if load.skill_names != ["explore-codebase"]
    ]

    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    assert not result.passed
    check = result.evidence["checks"]["explore-api after explore-codebase"]
    assert check["passed"] is False
    assert "never loaded successfully" in check["detail"]
    edge = next(
        e for e in result.evidence["skill_dag"]["edge_results"]
        if e["from"] == "explore-codebase" and e["to"] == "explore-api"
    )
    assert edge["verdict"] == "violated_dependency_missing"
    # It IS counted in the order-violated violation's edge list.
    order_violation = next(v for v in result.violations if v.code == "skill_dependency_order_violated")
    assert "explore-api after explore-codebase" in order_violation.message
    # explore-codebase's own missing-skill failure is skill_not_loaded's job.
    assert "skill_not_loaded" in [v.code for v in result.violations]


def test_skills_loaded_dag_vacuous_when_dependent_never_loaded(snapshot, contract):
    # Neither the dependent ("javascript") nor the dependency ("markup") ever
    # loads -- case 1: vacuously satisfied, not an order violation.
    contract = _with_deps(contract, {"javascript": ["markup"]})
    snapshot.skill_loads = [
        load for load in snapshot.skill_loads if load.skill_names not in (["javascript"], ["markup"])
    ]

    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    check = result.evidence["checks"]["javascript after markup"]
    assert check["passed"] is True
    assert "not applicable" in check["detail"]
    edge = next(
        e for e in result.evidence["skill_dag"]["edge_results"]
        if e["from"] == "markup" and e["to"] == "javascript"
    )
    assert edge["verdict"] == "vacuous_dependent_never_loaded"
    # It is NOT counted in skill_dependency_order_violated's edge list --
    # either the violation is absent, or if present (from some other edge),
    # it never mentions this one.
    for violation in result.violations:
        if violation.code == "skill_dependency_order_violated":
            assert "javascript after markup" not in violation.message
    # javascript/markup being missing is still caught, just under
    # skill_not_loaded, not the dependency-order violation.
    assert "skill_not_loaded" in [v.code for v in result.violations]


def test_skills_loaded_dag_tie_same_batch_passes(snapshot, contract):
    # actions and markup batch-loaded together in one call -- no sub-call
    # ordering signal exists, so a tie must satisfy the dependency.
    contract = _with_deps(contract, {"markup": ["actions"]})
    loads = [
        load for load in snapshot.skill_loads if load.skill_names not in (["actions"], ["markup"])
    ]
    loads.insert(2, SkillLoadRecord(skill_names=["actions", "markup"], success=True))
    snapshot.skill_loads = loads

    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    check = result.evidence["checks"]["markup after actions"]
    assert check["passed"] is True
    edge = next(
        e for e in result.evidence["skill_dag"]["edge_results"]
        if e["from"] == "actions" and e["to"] == "markup"
    )
    assert edge["verdict"] == "satisfied"
    assert edge["from_position"] == edge["to_position"]


def test_skills_loaded_skill_dag_evidence_shape(snapshot, contract):
    contract = _with_deps(contract, {"explore-api": ["explore-codebase"]})
    result = SkillsLoadedPlugin().evaluate(snapshot, contract)
    dag = result.evidence["skill_dag"]

    assert dag["expected"]["nodes"] == [r.name for r in contract.skills.required]
    assert dag["expected"]["edges"] == [{"from": "explore-codebase", "to": "explore-api"}]

    assert len(dag["actual"]["events"]) == len(snapshot.skill_loads)
    for i, (event, load) in enumerate(zip(dag["actual"]["events"], snapshot.skill_loads)):
        assert event["position"] == i
        assert event["skill_names"] == load.skill_names
        assert event["success"] == load.success

    assert len(dag["edge_results"]) == 1
    edge = dag["edge_results"][0]
    assert edge["from"] == "explore-codebase"
    assert edge["to"] == "explore-api"
    label_passed = result.evidence["checks"]["explore-api after explore-codebase"]["passed"]
    assert (edge["verdict"] in ("satisfied", "vacuous_dependent_never_loaded")) == label_passed
