# Plan: Merge Violations Breakdown into TODO section + fix cross-run hook leakage

**Jira**: RHAIENG-6190 — improve conforma-analyze skill
**Branch**: skill/conforma

## Context / Problem Statement

Two issues found during rhoai-3.5 conforma report run:

**Issue 1 — Redundant two-section structure in TODO preview and full resolution guide.**
The output has a `## TODO` section (compact summary table with action counts, checkboxes, and anchor links) AND a separate `## Violations Breakdown` section (detailed TODO #N subsections with per-violation tables). Both are produced from the same `_compute_violation_buckets()` computation. The user sees duplicate information: same bucket names, same violation counts, same "TODO" terminology. When only 1 action exists (common case), a 1-row summary table pointing to the one section below it is pointless.

**Issue 2 — Cross-run leakage in validate-guide-links.sh stop hook.**
The hook uses `ls -dt ~/.conforma/20*` to find any run directory with a resolution guide, instead of checking only the active run via `.conforma-active` symlink. When a new run is active but hasn't produced a guide yet, the hook validates a guide from a previous run.

## Proposed structure (diagram)

```
BEFORE (two sections, redundant):                    AFTER (single section):
┌─────────────────────────────────┐                  ┌─────────────────────────────────┐
│ ## TODO                         │                  │ [metadata header]               │
│ > 1 action — 29 violations      │                  │                                 │
│ ┌──────────────────────────────┐│                  │ ## TODO                         │
│ │ # │ Action │ Violations │Done││ ← REMOVED        │ > 1 action — 29 violations      │
│ │ 1 │ Fix... │ 29         │[ ] ││                  │                                 │
│ └──────────────────────────────┘│                  │ ### TODO #1 — 29 violations...  │
├─────────────────────────────────┤                  │ [help text]                     │
│ [metadata header]               │                  │ [detailed per-violation table]   │
├─────────────────────────────────┤                  │ ---                             │
│ ## Violations Breakdown ← REMOVED                  │ ### TODO #2 — 0 expiring...     │
│ ### TODO #1 — 29 violations...  │                  │ [help text]                     │
│ [detailed per-violation table]  │                  │ [detailed per-violation table]   │
│ ---                             │                  │ ---                             │
│ ### TODO #2 — 0 expiring...     │                  │ ... (TODO #3–#5 as needed)      │
│ [detailed per-violation table]  │                  │ ---                             │
│ ---                             │                  │ - coverage summary line         │
│ ... (TODO #3–#5)                │                  │ - warnings/expiring/divergence  │
│ ---                             │                  └─────────────────────────────────┘
│ - coverage summary              │
│ - warnings/expiring/divergence  │                  Hook fix:
└─────────────────────────────────┘                  ┌──────────────────────────┐
                                                     │ validate-guide-links.sh  │
Hook (broken):                                       │                          │
┌──────────────────────────┐                         │ GUIDE = ~/.conforma/     │
│ validate-guide-links.sh  │                         │   .conforma-active/      │
│                          │                         │   conforma-resolution-   │
│ for dir in ls -dt 20*    │ ← finds ANY run         │   guide.md               │
│   if guide exists → use  │                         │                          │
└──────────────────────────┘                         │ (active run only)        │
                                                     └──────────────────────────┘
```

## Changes

### 1. `skills/conforma-analyze/scripts/guide_renderers.py`

**1a. Rename `render_key_takeaways()` → heading change only**

- Line 499: Change `"## Violations Breakdown"` → `"## TODO"`
- Add the summary preamble line (currently in `render_todo()`) between the heading and the first TODO #N subsection. Compute it from the existing `buckets` data already available in this function:
  - Count non-empty bucket categories (no_mr, expiring_no_mr, expiring_mr_insufficient, has_mr, tooling, expiring_soon, upcoming_violations) → action count
  - Sum violation-bearing buckets → violations needing attention
  - Emit `> **N action(s)** required — M violation(s) need attention` (or `> No actions required — all violations are covered` if empty)
- Insert the summary line at lines ~499-500, after `## TODO` heading and before the tooling health line/first TODO #N subsection

**1b. Delete `render_todo()` function (lines 371–463)**

This function is fully replaced by the summary preamble added to `render_key_takeaways()`.

**1c. Update `write_todo_preview()` (lines 1365–1386)**

- Remove the `todo` parameter
- Change sections list from `[todo, metadata_header, key_takeaways]` to `[metadata_header, key_takeaways]`
- Metadata header comes first, then `## TODO` (which is now inside key_takeaways)

### 2. `skills/conforma-analyze/scripts/generate_resolution_guide.py`

**2a. Remove `render_todo()` call and import**

- Line 60: Remove `from guide_renderers import render_todo as _render_todo`
- Line 277: Remove `todo = _render_todo(...)` call

**2b. Update `sections` list for full guide (lines 279–289)**

- Remove `todo` from the sections list (it was the first element)
- `key_takeaways` (which now starts with `## TODO`) becomes the third element (after metadata_header)

**2c. Update `write_todo_preview()` call (lines 293–299)**

- Remove `todo=todo` argument

### 3. `hooks/validate-guide-links.sh` (already done)

Replace the `ls -dt` glob search (lines 34–42) with `.conforma-active` symlink lookup:
```bash
ACTIVE_DIR="$HOME/.conforma/.conforma-active"
if [ -L "$ACTIVE_DIR" ] && [ -d "$ACTIVE_DIR" ]; then
    GUIDE="$ACTIVE_DIR/conforma-resolution-guide.md"
    [ -f "$GUIDE" ] || GUIDE=""
else
    GUIDE=""
fi
```

### 4. Documentation updates

**4a. `skills/conforma/SKILL.md`**

- Line 75: Change `"Violations Breakdown" not "Executive Summary" or "Key Takeaways"` → `"TODO" not "Executive Summary" or "Key Takeaways" or "Violations Breakdown"`
- Line 84: Change `Reports must have TODO above Context Confirmation, followed by Violations Breakdown above main table` → `Reports must have Context Confirmation (metadata) above TODO; the TODO section contains the summary preamble and all TODO #N subsections`

**4b. `skills/conforma-analyze/SKILL.md`**

- Line 105: No change needed — rule about violation counts still applies to TODO section

**4c. `skills/conforma-analyze/workflows/full-analysis.md`**

- Line 198: Update "This file contains the TODO action items, metadata header (context confirmation), and violations breakdown tables" → "This file contains the metadata header (context confirmation) and the TODO section with summary preamble and all TODO #N subsections"

### 5. Test updates

**File: `tests/unit/test_conforma_analyze_generate_resolution_guide.py`**

**5a. `TestRenderTodo` class (lines 2774–2913) — DELETE entirely**

All 14 test methods test `render_todo()` which is being removed. The behavior they tested (summary counts, tooling rows, warnings rows, anchor links) moves into `render_key_takeaways()` and is tested there.

**5b. `TestKeyTakeawaysRename` class (lines 2920–2931) — UPDATE**

- `test_heading_is_violations_breakdown`: Update assertion from `## Violations Breakdown` to `## TODO`
- Rename class to `TestKeyTakeawaysHeading` or similar

**5c. `TestTodoPreviewContent` class (lines 3119–3164) — UPDATE**

- `test_todo_section_appears_first`: Update — metadata should come first now, then `## TODO`
- `test_todo_section_empty_string_omitted`: Remove — `todo` param no longer exists
- `test_todo_anchors_resolve`: Update to test anchors within the single `key_takeaways` output (no more cross-section resolution)
- Update `write_todo_preview()` calls to remove `todo=` parameter

**5d. ADD new tests for the summary preamble in `render_key_takeaways()`**

Port the essential behavior from deleted `TestRenderTodo` tests:
- Summary line shows correct action count and violation count
- "No actions required" when all covered
- Non-zero buckets appear in summary count
- Tooling unhealthy mentioned (if adding to preamble)
- Warnings mentioned (if adding to preamble)

**5e. Remove `render_todo` from imports (line 19)**

### 6. Plan file

Copy this plan to `skills/conforma-analyze/.plans/merge-violations-breakdown-into-todo.md`

## Verification

1. Run unit tests: `python -m pytest tests/unit/test_conforma_analyze_generate_resolution_guide.py -v`
2. Run a full conforma-analyze workflow for any release (e.g. `rhoai-3.5`)
3. Verify `conforma-todo.md` structure:
   - Starts with metadata header
   - Followed by `## TODO` with summary preamble line
   - Followed by `### TODO #1`, `### TODO #2`, etc.
   - NO `## Violations Breakdown` heading anywhere
   - NO separate summary table with Action/Violations/Done columns
4. Verify full resolution guide (`conforma-resolution-guide.md`) has same structure
5. Verify anchor links (`#todo-1`, etc.) work within the combined section
6. Verify the stop hook only validates the active run's guide (already tested)
