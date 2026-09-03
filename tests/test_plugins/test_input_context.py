from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.models.workflow_contract import ToolCheck
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


def test_input_context_reports_input_gathering_time_without_affecting_score(snapshot, contract):
    # Informational only -- added after scoring, so it must never turn a
    # would-be-clean pass into a partial score.
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    time_check = result.evidence["checks"]["input gathering time"]
    assert time_check["passed"] is True
    assert "call(s)" in time_check["detail"]


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
            input={"file_paths": ["services/petstore/designtime/petstore_apiTarget.json"]},
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
                "paths": ["/services/petstore/designtime/petstore_apiTarget.json"],
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


def test_input_context_flags_failed_read_as_not_retrieved(snapshot, contract):
    # The tool call referenced the right path, but errored out -- the content
    # was never actually delivered, so this must not count as "retrieved".
    for span in snapshot.spans:
        if span.id == "span-read-files":
            span.success = False
            span.error_message = "file not found"
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "context_path_read_failed" in codes
    assert "context_path_not_retrieved" not in codes
    entry = result.evidence["entries"][_RESOURCE]
    assert entry["retrieved"] is False
    assert "read failed" in entry["reason"]


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
    # The term must show up via a *read*-tool call's output -- a write tool
    # (e.g. edit_file_content) carrying it wouldn't count, since `terms` is
    # scoped to INPUT_GATHERING_TOOLS.
    for span in snapshot.spans:
        if span.id == "span-read-files":
            span.input = {"paths": span.input["paths"]}
            span.output = {"result": "resolved operationId petstore_findPetsByTags"}
        if span.id in ("span-create-var", "span-variable-write"):
            span.input = {k: v for k, v in span.input.items() if k != "operationId"}
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.passed
    entry = result.evidence["entries"][_RESOURCE]
    assert "petstore_findPetsByTags" in entry["found_terms"]
    assert entry["term_locations"]["petstore_findPetsByTags"] == "output only"


def test_input_context_ignores_term_in_write_tool_call(snapshot, contract):
    # A term appearing only in a write-tool call's input/output must NOT
    # ground the term -- `terms` under input_context is scoped to read tools
    # only; write-tool evidence belongs to `match`/output.py instead.
    for span in snapshot.spans:
        if span.id == "span-read-files":
            span.input = {"paths": span.input["paths"]}
        if span.id in ("span-create-var", "span-variable-write"):
            span.input = {k: v for k, v in span.input.items() if k != "operationId"}
        if span.id == "span-variable-write":
            span.output = {"result": "resolved operationId petstore_findPetsByTags"}
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert not result.passed
    entry = result.evidence["entries"][_RESOURCE]
    assert "petstore_findPetsByTags" in entry["missing_terms"]


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


def test_input_context_does_not_fail_on_unrelated_reads_when_no_scope_declared(snapshot, contract):
    # Regression: with input_context AND knowledge both empty, the contract
    # has expressed no opinion about what should be read -- an unrelated read
    # must be reported informationally, not fail the plugin. Previously this
    # was the *only* check in the plugin's checks map in this scenario, so a
    # single scope-creep flag zeroed out the whole plugin's score (0%),
    # regardless of every other (declared, passing) resource being fine.
    bare_contract = contract.model_copy(update={"input_context": [], "knowledge": []})
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

    result = InputContextPlugin().evaluate(snapshot, bare_contract)

    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    # The fixture's own petstore read is now unrelated too, once input_context
    # (which normally declares it) is cleared -- not the point of this test,
    # just a side effect of removing that declaration.
    assert "src/main/webapp/pages/OtherPage/OtherPage.html" in result.evidence["unrelated_reads"]
    check = result.evidence["checks"]["unrelated reads"]
    assert check["passed"] is True
    assert "not enforced" in check["detail"]


def test_input_context_still_enforces_scope_when_knowledge_alone_is_declared(snapshot, contract):
    # A contract can opt into enforcement via `knowledge` alone, without any
    # input_context entries -- it's still expressing an opinion about scope.
    knowledge_only_contract = contract.model_copy(
        update={"input_context": [], "knowledge": ["/catalog/some-doc.md"]}
    )
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

    result = InputContextPlugin().evaluate(snapshot, knowledge_only_contract)

    assert not result.passed
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" in codes
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
    # NotificationAction.md is deliberately NOT used here -- it's since been
    # added to the contract's `knowledge` list, so it's no longer a valid
    # "not allowed" example. ShowDialogAction.md stays outside `knowledge`.
    assert "/catalog/actions/ShowDialogAction/ShowDialogAction.md" not in contract.knowledge
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
            input={"file_paths": ["/catalog/actions/ShowDialogAction/ShowDialogAction.md"]},
            output=None,
            success=True,
        )
    )
    result = InputContextPlugin().evaluate(snapshot, contract)
    assert result.evidence["unrelated_reads"] == ["/catalog/actions/ShowDialogAction/ShowDialogAction.md"]
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


def test_input_context_does_not_flag_reads_matching_tool_check_match_value(snapshot, contract):
    # A read whose path is only declared via a ToolCheck's own `match:` value
    # (not via any `resource:` entry) shouldn't be flagged as scope creep --
    # writing that literal path already declares it as expected context.
    contract_with_tool_check = contract.model_copy(
        update={
            "input_context": [
                *contract.input_context,
                ToolCheck(tool="read_files", match=[["src/main/webapp/pages/OtherPage/OtherPage.html"]]),
            ]
        }
    )
    snapshot.spans.append(
        SpanRecord(
            id="span-read-declared-via-tool-check",
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
    result = InputContextPlugin().evaluate(snapshot, contract_with_tool_check)
    assert result.evidence["unrelated_reads"] == []
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" not in codes
