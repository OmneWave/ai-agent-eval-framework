import pytest

from wm_agents_validator.cli.compare_traces import _resolve_contract_trace_groups


def test_single_contract_pools_all_trace_id_groups():
    groups = _resolve_contract_trace_groups(
        ["contracts/a.yaml"], ["id1,id2", "id3"]
    )

    assert groups == [("contracts/a.yaml", ["id1", "id2", "id3"])]


def test_single_contract_single_trace_ids_group():
    groups = _resolve_contract_trace_groups(["contracts/a.yaml"], ["id1, id2"])

    assert groups == [("contracts/a.yaml", ["id1", "id2"])]


def test_multiple_contracts_are_paired_pairwise_in_order():
    groups = _resolve_contract_trace_groups(
        ["contracts/a.yaml", "contracts/b.yaml"], ["id1,id2", "id3,id4"]
    )

    assert groups == [
        ("contracts/a.yaml", ["id1", "id2"]),
        ("contracts/b.yaml", ["id3", "id4"]),
    ]


def test_multiple_contracts_require_matching_trace_ids_count():
    with pytest.raises(ValueError):
        _resolve_contract_trace_groups(
            ["contracts/a.yaml", "contracts/b.yaml"], ["id1,id2"]
        )
