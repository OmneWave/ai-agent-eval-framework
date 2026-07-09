import json

from wm_agents_validator.comparison.aggregator import merge_reports
from wm_agents_validator.models.comparison import (
    ComparisonReport,
    ComparisonRow,
    PluginScore,
    PluginViolation,
)
from wm_agents_validator.report.html_comparison_renderer import HtmlComparisonRenderer


def _extract_embedded_data(html: str) -> dict:
    start = html.index('<script id="comparison-data" type="application/json">') + len(
        '<script id="comparison-data" type="application/json">'
    )
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def test_render_embeds_valid_json_data_block():
    report = ComparisonReport(
        contract_id="test-contract",
        rows=[
            ComparisonRow(
                trace_id="trace-1",
                model_name="gpt-4",
                overall_score=1.0,
                passed=True,
                plugin_scores=[PluginScore(plugin="skills_loaded", passed=True, score=1.0)],
            ),
            ComparisonRow(trace_id="trace-2", status="error", error_message="timeout"),
        ],
    )

    html = HtmlComparisonRenderer().render(report)

    assert "<!DOCTYPE html>" in html
    assert "__COMPARISON_DATA_JSON__" not in html

    embedded = _extract_embedded_data(html)

    assert embedded["contract_id"] == "test-contract"
    assert len(embedded["rows"]) == 2
    assert embedded["rows"][0]["trace_id"] == "trace-1"
    assert embedded["rows"][1]["error_message"] == "timeout"


def test_render_escapes_closing_script_tags_in_data():
    report = ComparisonReport(
        contract_id="c",
        rows=[
            ComparisonRow(
                trace_id="trace-1",
                plugin_scores=[
                    PluginScore(
                        plugin="input_context",
                        passed=False,
                        score=0.0,
                        violations=[
                            PluginViolation(
                                code="evil",
                                message="evil</script><script>alert(1)</script>",
                            )
                        ],
                    )
                ],
            )
        ],
    )

    html = HtmlComparisonRenderer().render(report)

    assert "</script><script>alert(1)" not in html
    # The data must still round-trip to the original string once parsed as JSON.
    embedded = _extract_embedded_data(html)
    assert (
        embedded["rows"][0]["plugin_scores"][0]["violations"][0]["message"]
        == "evil</script><script>alert(1)</script>"
    )


def test_render_embeds_violation_resource_for_client_side_dedup():
    # `resource` links a violation back to the PluginCheck it explains (for
    # client-side dedup against checkLabels) -- it must survive into the
    # embedded JSON, not just live on the Python model.
    report = ComparisonReport(
        contract_id="c",
        rows=[
            ComparisonRow(
                trace_id="trace-1",
                plugin_scores=[
                    PluginScore(
                        plugin="input_context",
                        passed=True,
                        score=0.82,
                        violations=[
                            PluginViolation(
                                code="unrelated_context_fetched",
                                message="scope creep",
                                resource="unrelated reads",
                            )
                        ],
                    )
                ],
            )
        ],
    )

    html = HtmlComparisonRenderer().render(report)

    embedded = _extract_embedded_data(html)
    assert (
        embedded["rows"][0]["plugin_scores"][0]["violations"][0]["resource"] == "unrelated reads"
    )


def test_render_includes_heatmap_and_contract_data_for_multi_contract_report():
    report_a = ComparisonReport(
        contract_id="contract-a",
        rows=[
            ComparisonRow(
                trace_id="trace-1",
                contract_id="contract-a",
                model_name="gpt-4",
                overall_score=1.0,
                passed=True,
                plugin_scores=[PluginScore(plugin="skills_loaded", passed=True, score=1.0)],
            )
        ],
    )
    report_b = ComparisonReport(
        contract_id="contract-b",
        rows=[
            ComparisonRow(
                trace_id="trace-2",
                contract_id="contract-b",
                model_name="claude",
                overall_score=0.5,
                passed=False,
                plugin_scores=[PluginScore(plugin="skills_loaded", passed=False, score=0.5)],
            )
        ],
    )
    merged = merge_reports([report_a, report_b])

    html = HtmlComparisonRenderer().render(merged)

    # The table/heatmap themselves are built client-side from embedded data
    # (so the column set can adapt to what actually varies) -- verify the
    # static scaffolding + client-side field list are present, and that the
    # data needed to distinguish contracts/models made it into the payload.
    assert 'id="heatmap-container"' in html
    assert 'id="heatmap-group-by"' in html
    assert 'id="contract-filter"' in html
    assert "SHARED_CONTEXT_FIELDS" in html
    assert "contract_id" in html and "model_name" in html

    embedded = _extract_embedded_data(html)
    assert sorted(r["contract_id"] for r in embedded["rows"]) == ["contract-a", "contract-b"]
    assert embedded["contract_id"] == "contract-a, contract-b"


def test_render_trace_id_is_not_a_standalone_column_but_stays_in_drilldown_data():
    report = ComparisonReport(
        contract_id="c",
        rows=[ComparisonRow(trace_id="trace-should-be-in-drilldown-only")],
    )

    html = HtmlComparisonRenderer().render(report)

    # No static "Trace"/"Trace ID" column header should exist in the markup;
    # the id is only surfaced via embedded data for the drill-down + the "#"
    # index tooltip, not as a prominent top-level column.
    assert "<th>Trace</th>" not in html
    assert '<th data-key="trace_id">' not in html
    embedded = _extract_embedded_data(html)
    assert embedded["rows"][0]["trace_id"] == "trace-should-be-in-drilldown-only"
