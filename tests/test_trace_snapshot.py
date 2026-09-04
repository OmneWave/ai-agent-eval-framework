from wm_agents_validator.models.trace_snapshot import (
    SpanRecord,
    TraceSnapshot,
    extract_paths_from_input,
    resolve_dotted_tool_calls,
)


# ── Schema-accurate extraction, keyed by real tool name ──────────────────────
# Field names below are taken directly from each tool's @tool-decorated
# signature in wm-agent-server's src/tools.py.

def test_read_files_uses_file_paths_list():
    tool_input = {"file_paths": ["src/main/webapp/pages/PetTable/PetTable.html"]}
    assert extract_paths_from_input(tool_input, "read_files") == [
        "src/main/webapp/pages/PetTable/PetTable.html"
    ]


def test_read_files_with_multiple_paths():
    tool_input = {"file_paths": ["a.html", "b.js"]}
    assert extract_paths_from_input(tool_input, "read_files") == ["a.html", "b.js"]


def test_write_file_uses_file_path():
    tool_input = {"file_path": "a.html", "file_content": "<div></div>"}
    assert extract_paths_from_input(tool_input, "write_file") == ["a.html"]


def test_edit_file_content_uses_file_path():
    tool_input = {"file_path": "a.html", "old_string": "x", "new_string": "y"}
    assert extract_paths_from_input(tool_input, "edit_file_content") == ["a.html"]


def test_delete_file_uses_file_path():
    assert extract_paths_from_input({"file_path": "a.html"}, "delete_file") == ["a.html"]


def test_get_file_diagnostics_uses_file_path():
    assert extract_paths_from_input({"file_path": "a.html"}, "get_file_diagnostics") == [
        "a.html"
    ]


def test_get_file_patch_for_checkpoints_uses_file_path():
    tool_input = {"start_checkpoint": "code_0", "end_checkpoint": "code_1", "file_path": "a.html"}
    assert extract_paths_from_input(tool_input, "get_file_patch_for_checkpoints") == ["a.html"]


def test_find_files_by_glob_uses_folder_path():
    tool_input = {"pattern": "**/*.java", "folder_path": "src/main/java"}
    assert extract_paths_from_input(tool_input, "find_files_by_glob") == ["src/main/java"]


def test_grep_in_files_uses_path():
    tool_input = {"regex_pattern": "foo", "path": "src/main/webapp"}
    assert extract_paths_from_input(tool_input, "grep_in_files") == ["src/main/webapp"]


def test_vcs_file_updated_uses_file_path():
    tool_input = {"file_path": "src/main/webapp/pages/Cards_1/Cards_1.variables.json"}
    assert extract_paths_from_input(tool_input, "vcs_file_updated") == [
        "src/main/webapp/pages/Cards_1/Cards_1.variables.json"
    ]


# ── Fallback heuristic for unknown tools (e.g. MCP tools reached via ────────
# execute_tool, whose schemas live outside this repo) ────────────────────────

def test_unknown_tool_falls_back_to_generic_key_scan():
    assert extract_paths_from_input({"path": "a.json"}, "some_mcp_tool") == ["a.json"]
    assert extract_paths_from_input({"file_path": "b.json"}, "some_mcp_tool") == ["b.json"]
    assert extract_paths_from_input({"paths": ["a.json", "b.json"]}, "some_mcp_tool") == [
        "a.json",
        "b.json",
    ]


def test_no_tool_name_falls_back_to_generic_key_scan():
    assert extract_paths_from_input({"path": "a.json"}) == ["a.json"]
    assert extract_paths_from_input({"file_paths": ["a.json"]}) == ["a.json"]


def test_fallback_change_regex():
    tool_input = {"change": "Updating src/main/webapp/pages/PetTable/PetTable.js now"}
    assert extract_paths_from_input(tool_input) == [
        "src/main/webapp/pages/PetTable/PetTable.js"
    ]


def test_known_tool_with_missing_field_still_falls_back():
    # If a known tool's payload is missing its usual field (malformed/unexpected
    # shape), we shouldn't silently return nothing if another common key is present.
    tool_input = {"path": "a.json"}
    assert extract_paths_from_input(tool_input, "write_file") == ["a.json"]


def test_extract_paths_from_input_empty():
    assert extract_paths_from_input({}) == []
    assert extract_paths_from_input({}, "read_files") == []


# ── A failed tool call never counts as a real change/match ──────────────────
# Seeing the right path/arguments in a call that then errored out isn't
# evidence the write/tool-invocation actually happened.

def test_file_changes_excludes_failed_write_call():
    snapshot = TraceSnapshot(
        trace_id="t1",
        entry_agent="a",
        status="success",
        skill_loads=[],
        spans=[
            SpanRecord(
                id="s1",
                name="write_file",
                type="TOOL",
                parent_id=None,
                agent_id="a",
                input={"file_path": "src/main/webapp/pages/Login/Login.html"},
                output=None,
                success=False,
            ),
        ],
    )
    assert snapshot.file_changes == []


def test_file_changes_includes_successful_write_call():
    snapshot = TraceSnapshot(
        trace_id="t2",
        entry_agent="a",
        status="success",
        skill_loads=[],
        spans=[
            SpanRecord(
                id="s1",
                name="write_file",
                type="TOOL",
                parent_id=None,
                agent_id="a",
                input={"file_path": "src/main/webapp/pages/Login/Login.html"},
                output=None,
                success=True,
            ),
        ],
    )
    assert [fc.path for fc in snapshot.file_changes] == ["src/main/webapp/pages/Login/Login.html"]


def test_file_changes_permissive_when_success_unset():
    snapshot = TraceSnapshot(
        trace_id="t3",
        entry_agent="a",
        status="success",
        skill_loads=[],
        spans=[
            SpanRecord(
                id="s1",
                name="write_file",
                type="TOOL",
                parent_id=None,
                agent_id="a",
                input={"file_path": "src/main/webapp/pages/Login/Login.html"},
                output=None,
                success=None,
            ),
        ],
    )
    assert [fc.path for fc in snapshot.file_changes] == ["src/main/webapp/pages/Login/Login.html"]


def test_resolve_dotted_tool_calls_excludes_failed_span():
    spans = [
        SpanRecord(
            id="s1",
            name="execute_tool",
            type="TOOL",
            parent_id=None,
            agent_id="a",
            input={"tool_name": "ui_applyChangesOnPageMarkup", "tool_args": {"pageName": "Login"}},
            output=None,
            success=False,
        ),
    ]
    assert resolve_dotted_tool_calls(spans, "execute_tool.ui_applyChangesOnPageMarkup") == []


def test_resolve_dotted_tool_calls_includes_successful_span():
    spans = [
        SpanRecord(
            id="s1",
            name="execute_tool",
            type="TOOL",
            parent_id=None,
            agent_id="a",
            input={"tool_name": "ui_applyChangesOnPageMarkup", "tool_args": {"pageName": "Login"}},
            output=None,
            success=True,
        ),
    ]
    assert resolve_dotted_tool_calls(spans, "execute_tool.ui_applyChangesOnPageMarkup") == [{"pageName": "Login"}]
