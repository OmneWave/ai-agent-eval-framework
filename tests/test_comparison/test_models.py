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


def test_filtered_by_user_prompt_is_case_insensitive_substring_match():
    report = ComparisonReport(
        contract_id="c",
        rows=[
            ComparisonRow(trace_id="1", user_prompt="Bind widget in PetTable to findByTags endpoint"),
            ComparisonRow(trace_id="2", user_prompt="Create a CustomerTable page"),
            ComparisonRow(trace_id="3", user_prompt=None),
        ],
    )

    filtered = report.filtered_by_user_prompt("findbytags")

    assert [r.trace_id for r in filtered.rows] == ["1"]
    assert len(report.rows) == 3  # original untouched


def test_filtered_by_user_prompt_excludes_rows_with_no_prompt():
    report = ComparisonReport(contract_id="c", rows=[ComparisonRow(trace_id="1", user_prompt=None)])

    filtered = report.filtered_by_user_prompt("anything")

    assert filtered.rows == []


def test_filtered_by_skill_name_is_case_insensitive_substring_match():
    report = ComparisonReport(
        contract_id="c",
        rows=[
            ComparisonRow(trace_id="1", skill_names=["ui_to_api_binding_workflow", "explore-api"]),
            ComparisonRow(trace_id="2", skill_names=["screenshot-to-wavemaker-web"]),
            ComparisonRow(trace_id="3", skill_names=[]),
        ],
    )

    filtered = report.filtered_by_skill_name("API_BINDING")

    assert [r.trace_id for r in filtered.rows] == ["1"]
    assert len(report.rows) == 3  # original untouched


def test_filtered_by_skill_name_excludes_rows_with_no_skills():
    report = ComparisonReport(contract_id="c", rows=[ComparisonRow(trace_id="1", skill_names=[])])

    filtered = report.filtered_by_skill_name("anything")

    assert filtered.rows == []
