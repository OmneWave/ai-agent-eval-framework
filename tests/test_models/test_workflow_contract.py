import pytest
from pydantic import ValidationError

from wm_agents_validator.models.workflow_contract import SkillRequirement, SkillsSpec


def test_required_normalizes_bare_string():
    spec = SkillsSpec(required="x")
    assert spec.required == [SkillRequirement(name="x")]
    assert spec.required[0].depends_on == []


def test_required_normalizes_flat_string_list():
    spec = SkillsSpec(required=["x", "y"])
    assert spec.required == [SkillRequirement(name="x"), SkillRequirement(name="y")]


def test_required_normalizes_mixed_list():
    spec = SkillsSpec(required=["x", {"name": "y", "depends_on": ["x"]}])
    assert spec.required[0] == SkillRequirement(name="x")
    assert spec.required[1] == SkillRequirement(name="y", depends_on=["x"])


def test_required_rejects_unknown_dependency_reference():
    with pytest.raises(ValidationError, match="unknown skill 'z'"):
        SkillsSpec(required=[{"name": "y", "depends_on": ["z"]}])


def test_required_rejects_dependency_on_optional_only_skill():
    # depends_on may only reference another `required` skill -- confirms the
    # scoping rule is actually enforced (an optional-only name is never in
    # the required name set, so it's rejected via the same unknown-reference
    # path), not just documented.
    with pytest.raises(ValidationError, match="unknown skill 'z'"):
        SkillsSpec(required=[{"name": "y", "depends_on": ["z"]}], optional=["z"])


def test_required_rejects_self_dependency():
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        SkillsSpec(required=[{"name": "x", "depends_on": ["x"]}])


def test_required_rejects_two_node_cycle():
    with pytest.raises(ValidationError, match="dependency cycle detected"):
        SkillsSpec(
            required=[
                {"name": "a", "depends_on": ["b"]},
                {"name": "b", "depends_on": ["a"]},
            ]
        )


def test_required_rejects_longer_cycle():
    with pytest.raises(ValidationError, match="dependency cycle detected"):
        SkillsSpec(
            required=[
                {"name": "a", "depends_on": ["b"]},
                {"name": "b", "depends_on": ["c"]},
                {"name": "c", "depends_on": ["a"]},
            ]
        )


def test_required_rejects_duplicate_name():
    with pytest.raises(ValidationError, match="duplicate skill name 'x'"):
        SkillsSpec(required=["x", "x"])


def test_required_allows_dependency_declared_later_in_list():
    # Declaration order in YAML doesn't matter -- only graph structure.
    spec = SkillsSpec(required=[{"name": "b", "depends_on": ["a"]}, "a"])
    assert [r.name for r in spec.required] == ["b", "a"]
