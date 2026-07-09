from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.plugins.input_context import InputContextPlugin

_RESOURCE = "api.petstore.petstore_findPetsByTags"


def test_input_context_passes_with_fixture(snapshot, contract):
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    entry = result.evidence["entries"][_RESOURCE]
    assert entry["retrieved"] is True
    assert entry["missing_terms"] == []
    assert result.evidence["checks"]["unrelated reads"] == {
        "passed": True,
        "detail": "no unrelated files read",
    }
    # This contract's output entries have no trailing qualifier segments, so
    # there's nothing for the "output qualifiers" rollup to check.
    assert "output qualifiers" not in result.evidence["checks"]


def test_input_context_recognizes_file_paths_key_reads(snapshot, contract):
    # Regression: real read_files tool calls shape their input as
    # {"file_paths": [...]} (plural, snake_case).
    snapshot.spans.append(
        SpanRecord(
            id="span-extra-read",
            name="read_files",
            type="TOOL",
            parent_id="span-deleg-backend",
            agent_id="wm_backend_expert",
            timestamp="2026-01-01T10:00:05Z",
            end_time=None,
            level="DEFAULT",
            input={"file_paths": ["services/petstore/designtime/petstore_API_REST_SERVICE.json"]},
            output=None,
            success=True,
        )
    )
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.passed


def test_input_context_matches_path_regardless_of_leading_slash(snapshot, contract):
    for span in snapshot.spans:
        if span.id == "span-read-files":
            span.input = {
                "paths": ["/services/petstore/designtime/petstore_API_REST_SERVICE.json"],
                "operationId": "petstore_findPetsByTags",
            }
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.evidence["entries"][_RESOURCE]["retrieved"] is True


def test_input_context_flags_missing_path(snapshot, contract):
    snapshot.spans = [s for s in snapshot.spans if s.id != "span-read-files"]
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "context_path_not_retrieved" in codes
    entry = result.evidence["entries"][_RESOURCE]
    assert entry["retrieved"] is False
    assert "never retrieved" in entry["reason"]


def test_input_context_flags_deviation_and_fails(snapshot, contract):
    # File is still read, but the term never surfaces anywhere -> under the
    # strict scoring rule, this now fails the plugin too (no partial credit).
    for span in snapshot.spans:
        if span.id == "span-read-files":
            span.input = {"paths": span.input["paths"]}
        if span.id in ("span-create-var", "span-variable-write"):
            span.input = {k: v for k, v in span.input.items() if k != "operationId"}
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert not result.passed
    assert result.score < 1.0
    codes = [v.code for v in result.violations]
    assert "context_deviation" in codes
    assert "context_path_not_retrieved" not in codes
    entry = result.evidence["entries"][_RESOURCE]
    assert "petstore_findPetsByTags" in entry["missing_terms"]


def test_input_context_finds_term_in_tool_output_only(snapshot, contract):
    for span in snapshot.spans:
        if span.id == "span-read-files":
            span.input = {"paths": span.input["paths"]}
        if span.id in ("span-create-var", "span-variable-write"):
            span.input = {k: v for k, v in span.input.items() if k != "operationId"}
        if span.id == "span-variable-write":
            span.output = {"result": "resolved operationId petstore_findPetsByTags"}
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.passed
    entry = result.evidence["entries"][_RESOURCE]
    assert "petstore_findPetsByTags" in entry["found_terms"]
    assert entry["term_locations"]["petstore_findPetsByTags"] == "output only"


def test_input_context_flags_unrelated_file_read(snapshot, contract):
    snapshot.spans.append(
        SpanRecord(
            id="span-read-unrelated",
            name="read_files",
            type="TOOL",
            parent_id="span-deleg-ui",
            agent_id="wm_ui_expert",
            timestamp="2026-01-01T10:00:11Z",
            end_time=None,
            level="DEFAULT",
            input={"file_paths": ["src/main/webapp/pages/OtherPage/OtherPage.html"]},
            output=None,
            success=True,
        )
    )
    result = InputContextPlugin().evaluate(snapshot, contract)
    # Under the strict scoring rule, scope creep now fails the plugin too.
    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" in codes
    assert result.evidence["unrelated_reads"] == ["src/main/webapp/pages/OtherPage/OtherPage.html"]
    assert result.evidence["checks"]["unrelated reads"]["passed"] is False


def test_input_context_does_not_flag_knowledge_reads(snapshot, contract):
    snapshot.spans.append(
        SpanRecord(
            id="span-read-catalog-docs",
            name="read_files",
            type="TOOL",
            parent_id="span-deleg-ui",
            agent_id="wm_ui_expert",
            timestamp="2026-01-01T10:00:11Z",
            end_time=None,
            level="DEFAULT",
            input={
                "file_paths": [
                    "/catalog/components/wm-table-column/wm-table-column.md",
                    "/catalog/variables/ApiAwareVariable/ApiAwareVariable.md",
                    "/catalog/variables/variables-list.md",
                ]
            },
            output=None,
            success=True,
        )
    )
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.evidence["unrelated_reads"] == []


def test_input_context_flags_catalog_paths_not_in_knowledge(snapshot, contract):
    snapshot.spans.append(
        SpanRecord(
            id="span-read-catalog-not-allowed",
            name="read_files",
            type="TOOL",
            parent_id="span-deleg-ui",
            agent_id="wm_ui_expert",
            timestamp="2026-01-01T10:00:11Z",
            end_time=None,
            level="DEFAULT",
            input={"file_paths": ["/catalog/actions/NotificationAction/NotificationAction.md"]},
            output=None,
            success=True,
        )
    )
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.evidence["unrelated_reads"] == ["/catalog/actions/NotificationAction/NotificationAction.md"]
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" in codes


def test_input_context_does_not_flag_reads_matching_output_resource(snapshot, contract):
    # Re-reading a file that's declared under `output` isn't unrelated --
    # reading a file you're about to edit is normal.
    snapshot.spans.append(
        SpanRecord(
            id="span-read-other-resource-file",
            name="read_files",
            type="TOOL",
            parent_id="span-deleg-ui",
            agent_id="wm_ui_expert",
            timestamp="2026-01-01T10:00:11Z",
            end_time=None,
            level="DEFAULT",
            input={"file_paths": ["src/main/webapp/pages/PetTable/PetTable.variables.json"]},
            output=None,
            success=True,
        )
    )
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.evidence["unrelated_reads"] == []
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" not in codes


def test_input_context_ignores_search_tools_for_unrelated_check(snapshot, contract):
    snapshot.spans.append(
        SpanRecord(
            id="span-grep-unrelated",
            name="grep_in_files",
            type="TOOL",
            parent_id="span-deleg-ui",
            agent_id="wm_ui_expert",
            timestamp="2026-01-01T10:00:11Z",
            end_time=None,
            level="DEFAULT",
            input={"regex_pattern": "foo", "path": "src/main/webapp/pages/OtherPage"},
            output=None,
            success=True,
        )
    )
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.evidence["unrelated_reads"] == []
    assert result.score == 1.0
