# WM Bench — Issues & Future Requirements

---

## FR-1 — Trace-driven partial reference validation

**Type:** Feature Request
**Status:** Open

### Problem

The current output plugin validates partial creation and page HTML references using static, contract-declared resource names (e.g., `page.dashboardHeader`). This has two fundamental weaknesses:

1. **Names are generation-specific.** Partial names like `dashboardHeader`, `accountLeftnav` are whatever the agent chose in a given run. Contracts generated from one run break when the agent picks different names on the next run.

2. **Cannot distinguish agent-created vs pre-existing partials.** A `match: ['content=']` check on the main page HTML passes even if the agent reused a default project partial it didn't create. There is no way to assert "the agent created this partial AND wired it into the main page" using the current static contract model.

### Proposed Approach

Make partial reference validation trace-driven rather than contract-declared.

**Step 1 — Detect partial creation from `write_file` evidence:**

Scan `write_file` tool calls in the trace where:
- `file_path` matches `src/main/webapp/pages/*/**.html`
- `file_content` contains a root `<wm-partial>` element with a `type` attribute (`type="header"`, `type="leftnav"`, `type="rightnav"`, `type="footer"`, etc.)

Extract the partial name from the `name="..."` attribute on the `<wm-partial>` tag, or from the file path (`pages/accountHeader/accountHeader.html` → `accountHeader`).

Confirmed from trace data — the agent writes partial files like:

```
write_file: {
  file_path: 'src/main/webapp/pages/accountHeader/accountHeader.html',
  file_content: '<wm-partial name="accountHeader" type="header">...'
}
write_file: {
  file_path: 'src/main/webapp/pages/accountLeftnav/accountLeftnav.html',
  file_content: '<wm-partial name="accountLeftnav" type="leftnav">...'
}
```

**Step 2 — Verify reference in the main page HTML:**

Find the `write_file` call for the main page HTML and confirm it contains `content="{extractedName}"` — the WaveMaker attribute that binds a layout panel slot to a partial page.

### What this enables

- **Name-agnostic:** partial name is extracted dynamically from the trace, never declared in the contract
- **Type-aware:** can assert "a header-type partial was created AND referenced" separately from leftnav/rightnav/footer
- **Distinguishes agent-created vs pre-existing:** only `write_file` calls within this trace's evidence window count — pre-existing project partials the agent didn't touch are excluded
- **Closed chain:** the entire validation is within `write_file` evidence — no dependency on `platform_createWebPage` parameters

### Implementation Notes

- The `type` attribute is on the `<wm-partial>` root element inside the file content, not on a `platform_createWebPage` call parameter
- Both detection and reference-verification are anchored to `write_file` — already an output generation tool in `OUTPUT_GENERATION_TOOLS`
- Needs either a new wm-bench plugin or a new contract field type (e.g., `derived_assertions`) that expresses "for each write_file creating a wm-partial of type X, assert the main page write_file references it via content="
- Edge case: agent overwrites an existing partial — `write_file` still appears in trace, validation still works correctly
