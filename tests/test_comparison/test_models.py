from wm_agents_validator.models.comparison import ComparisonReport, ComparisonRow


def _row(trace_id: str, model_name: str | None) -> ComparisonRow:
    return ComparisonRow(trace_id=trace_id, model_name=model_name)


def test_model_names_are_unique_and_ordered_by_first_appearance():
    report = ComparisonReport(
        contract_id="c",
        rows=[_row("1", "gpt-4"), _row("2", "claude"), _row("3", "gpt-4"), _row("4", None)],
    )

    assert report.model_names == ["gpt-4", "claude"]


def test_filtered_by_model_is_case_insensitive_and_returns_new_report():
    report = ComparisonReport(
        contract_id="c", rows=[_row("1", "GPT-4"), _row("2", "claude")]
    )

    filtered = report.filtered_by_model("gpt-4")

    assert [r.trace_id for r in filtered.rows] == ["1"]
    assert len(report.rows) == 2  # original untouched


def test_row_is_error_property():
    assert _row("1", None).is_error is False
    assert ComparisonRow(trace_id="1", status="error").is_error is True
