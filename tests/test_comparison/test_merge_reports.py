import pytest

from wm_agents_validator.comparison.aggregator import merge_reports
from wm_agents_validator.models.comparison import ComparisonReport, ComparisonRow


def test_merge_reports_combines_rows_from_all_reports():
    report_a = ComparisonReport(
        contract_id="contract-a",
        rows=[ComparisonRow(trace_id="1", contract_id="contract-a")],
    )
    report_b = ComparisonReport(
        contract_id="contract-b",
        rows=[ComparisonRow(trace_id="2", contract_id="contract-b")],
    )

    merged = merge_reports([report_a, report_b])

    assert [r.trace_id for r in merged.rows] == ["1", "2"]
    assert merged.contract_id == "contract-a, contract-b"
    assert merged.contract_ids == ["contract-a", "contract-b"]


def test_merge_reports_single_report_keeps_its_contract_id_as_label():
    report = ComparisonReport(
        contract_id="only-contract",
        rows=[ComparisonRow(trace_id="1", contract_id="only-contract")],
    )

    merged = merge_reports([report])

    assert merged.contract_id == "only-contract"


def test_merge_reports_rejects_empty_list():
    with pytest.raises(ValueError):
        merge_reports([])
