import pytest

from wm_agents_validator.cli.compare_traces import (
    _resolve_contract_trace_groups,
    _split_contract_arg,
)


def test_split_contract_arg_bare_path_has_no_embedded_ids():
    assert _split_contract_arg("contracts/a.yaml") == ("contracts/a.yaml", [])


def test_split_contract_arg_splits_embedded_ids():
    assert _split_contract_arg("contracts/a.yaml:id1,id2") == ("contracts/a.yaml", ["id1", "id2"])


def test_split_contract_arg_strips_whitespace_around_ids():
    assert _split_contract_arg("contracts/a.yaml: id1 , id2 ") == ("contracts/a.yaml", ["id1", "id2"])


def test_single_bare_contract_pools_all_trace_id_groups():
    groups = _resolve_contract_trace_groups(
        ["contracts/a.yaml"], ["id1,id2", "id3"]
    )

    assert groups == [("contracts/a.yaml", ["id1", "id2", "id3"])]


def test_single_contract_single_trace_ids_group():
    groups = _resolve_contract_trace_groups(["contracts/a.yaml"], ["id1, id2"])

    assert groups == [("contracts/a.yaml", ["id1", "id2"])]


def test_single_contract_with_embedded_ids_and_no_trace_ids_flag():
    groups = _resolve_contract_trace_groups(["contracts/a.yaml:id1,id2"], [])

    assert groups == [("contracts/a.yaml", ["id1", "id2"])]


def test_single_contract_pools_embedded_ids_with_trace_ids_flag():
    groups = _resolve_contract_trace_groups(["contracts/a.yaml:id1,id2"], ["id3"])

    assert groups == [("contracts/a.yaml", ["id1", "id2", "id3"])]


def test_multiple_contracts_use_embedded_ids_each():
    groups = _resolve_contract_trace_groups(
        ["contracts/a.yaml:id1,id2", "contracts/b.yaml:id3,id4"], []
    )

    assert groups == [
        ("contracts/a.yaml", ["id1", "id2"]),
        ("contracts/b.yaml", ["id3", "id4"]),
    ]


def test_multiple_contracts_require_embedded_ids_on_every_one():
    with pytest.raises(ValueError):
        _resolve_contract_trace_groups(
            ["contracts/a.yaml:id1,id2", "contracts/b.yaml"], []
        )


def test_multiple_contracts_reject_separate_trace_ids_flag():
    with pytest.raises(ValueError):
        _resolve_contract_trace_groups(
            ["contracts/a.yaml:id1,id2", "contracts/b.yaml:id3,id4"], ["id5"]
        )


