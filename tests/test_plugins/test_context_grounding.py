from wm_agents_validator.models.trace_snapshot import SpanRecord
from wm_agents_validator.plugins.context_grounding import ContextGroundingPlugin


def test_context_grounding_recognizes_file_paths_key_reads(snapshot, contract):
    # Regression: real read_files tool calls shape their input as
    # {"file_paths": [...]} (plural, snake_case). This key was previously not
    # recognized by path extraction, so grounded reads shaped this way were
    # invisible and incorrectly reported as "never retrieved".
    snapshot.spans.append(
        SpanRecord(
            id="b1f8e6c82c405f47",
            name="read_files",
            type="TOOL",
            parent_id="be26d9df1410f151",
            agent_id="wm_ui_expert",
            timestamp="2026-07-06T06:31:16.127000Z",
            end_time="2026-07-06T06:31:16.153000Z",
            level="DEFAULT",
            input={"file_paths": ["src/main/webapp/pages/PetTable/PetTable.html"]},
            output=None,
            success=True,
        )
    )

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    widget_report = result.evidence["resources"]["widget"]
    assert "src/main/webapp/pages/PetTable/PetTable.html" in widget_report["retrieved_paths"]
    assert widget_report["missing_paths"] == []


def test_context_grounding_matches_path_regardless_of_leading_slash(snapshot, contract):
    # Tools sometimes report the same file as an absolute-looking path
    # ("/services/...") even though the contract declares it project-relative
    # ("services/..."), or vice versa. A leading slash mismatch alone must
    # never cause a false "never retrieved" violation.
    for span in snapshot.spans:
        if span.id == "span-read-files":
            span.input = {
                "paths": ["/services/petstore/designtime/petstore_API_REST_SERVICE.json"],
                "operationId": "petstore_findPetsByTags",
            }

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    assert result.passed
    assert result.score == 1.0
    apiservice_report = result.evidence["resources"]["apiservice"]
    assert apiservice_report["missing_paths"] == []
    # retrieved_paths reports the contract's own (unprefixed) declared path,
    # even though the tool call itself used a leading slash.
    assert (
        "services/petstore/designtime/petstore_API_REST_SERVICE.json"
        in apiservice_report["retrieved_paths"]
    )


def test_context_grounding_does_not_flag_unrelated_read_matching_by_slash_only(snapshot, contract):
    # A read that matches an expected path except for a leading slash isn't
    # "unrelated" either -- same underlying file, just reported differently.
    snapshot.spans.append(
        SpanRecord(
            id="span-read-leading-slash-variant",
            name="read_files",
            type="TOOL",
            parent_id="span-deleg-ui",
            agent_id="wm_ui_expert",
            timestamp="2026-01-01T10:00:11Z",
            end_time=None,
            level="DEFAULT",
            input={"file_paths": ["/src/main/webapp/pages/PetTable/PetTable.variables.json"]},
            output=None,
            success=True,
        )
    )

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    assert result.evidence["unrelated_reads"] == []
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" not in codes


def test_context_grounding_passes_with_fixture(snapshot, contract):
    result = ContextGroundingPlugin().evaluate(snapshot, contract)
    assert result.passed
    assert result.score == 1.0
    assert result.violations == []
    for resource_report in result.evidence["resources"].values():
        assert resource_report["missing_paths"] == []
        assert resource_report["missing_context"] == []


def test_context_grounding_flags_missing_path(snapshot, contract):
    # The apiservice reference file is never read by any tool in the trace.
    snapshot.spans = [s for s in snapshot.spans if s.id != "span-read-files"]

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    assert not result.passed
    assert result.score < 1.0
    codes = [v.code for v in result.violations]
    assert "context_path_not_retrieved" in codes

    apiservice_report = result.evidence["resources"]["apiservice"]
    assert apiservice_report["missing_paths"] == [
        "services/petstore/designtime/petstore_API_REST_SERVICE.json"
    ]
    assert "never retrieved" in apiservice_report["reason"]


def test_context_grounding_flags_deviation_without_hard_failure(snapshot, contract):
    # Files are still read/written, but the operation/service context terms
    # never surface anywhere in any tool call -> a softer "drift" signal.
    for span in snapshot.spans:
        if span.id == "span-read-files":
            span.input = {"paths": span.input["paths"]}
        if span.id == "span-create-var":
            span.input = {"tool": span.input["tool"], "path": span.input["path"]}

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    assert result.passed  # reference files were still grounded, so this isn't a hard failure
    assert result.score < 1.0
    codes = [v.code for v in result.violations]
    assert "context_deviation" in codes
    assert "context_path_not_retrieved" not in codes

    apiservice_report = result.evidence["resources"]["apiservice"]
    assert "petstore_findPetsByTags" in apiservice_report["missing_context"]


def test_context_grounding_skips_resources_without_files_or_context(snapshot, contract):
    result = ContextGroundingPlugin().evaluate(snapshot, contract)
    # Every resource in this contract declares files/context, so all three show up.
    assert set(result.evidence["resources"].keys()) == {"apiservice", "variable", "widget"}


def test_context_grounding_flags_unrelated_file_read(snapshot, contract):
    # An extra read_files call pulls in a page nowhere declared by any resource
    # in the contract -> should be flagged as scope creep and dilute the score,
    # without failing the plugin outright (reference files are still grounded).
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

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    assert result.passed  # unrelated reads are a soft signal, not a hard failure
    assert result.score < 1.0
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" in codes
    assert result.evidence["unrelated_reads"] == [
        "src/main/webapp/pages/OtherPage/OtherPage.html"
    ]


def test_context_grounding_does_not_flag_allowed_context_reads(snapshot, contract):
    # These exact catalog docs are declared as allowed_context_reads on the
    # contract -- reading them is legitimate exploration and must not be
    # flagged as unrelated scope creep.
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

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    assert result.passed
    assert result.score == 1.0
    assert result.evidence["unrelated_reads"] == []
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" not in codes


def test_context_grounding_flags_catalog_paths_not_in_allowlist(snapshot, contract):
    # allowed_context_reads is an explicit list, not a wildcard -- a catalog
    # path that isn't on it is still legitimate scope-creep signal.
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

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    assert result.evidence["unrelated_reads"] == [
        "/catalog/actions/NotificationAction/NotificationAction.md"
    ]
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" in codes


def test_context_grounding_does_not_flag_reads_matching_any_resource(snapshot, contract):
    # Re-reading a file that's already part of another resource's declared
    # scope isn't unrelated, even if it's not the current resource's own file.
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

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    assert result.evidence["unrelated_reads"] == []
    codes = [v.code for v in result.violations]
    assert "unrelated_context_fetched" not in codes


def test_context_grounding_ignores_search_tools_for_unrelated_check(snapshot, contract):
    # grep_in_files/find_files_by_glob only use a path as a search scope, not
    # as retrieved context, so they shouldn't count toward unrelated reads.
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

    result = ContextGroundingPlugin().evaluate(snapshot, contract)

    assert result.evidence["unrelated_reads"] == []
    assert result.score == 1.0
