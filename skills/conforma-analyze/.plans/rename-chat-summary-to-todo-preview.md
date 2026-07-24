# Rename "chat summary" → "TODO preview" to emphasize resolution guide as primary output

**Jira**: [RHAIENG-6190](https://redhat.atlassian.net/browse/RHAIENG-6190)  
**Builds on**: `skills/conforma-analyze/.plans/fix-guide-filename-and-todo-in-full-guide.md` (item #22)

## Context

**Previous work:**
- Item #20: Added TODO section, renamed "Executive Summary" heading → "Violations Breakdown"
- Item #22: Renamed all "executive summary" → "chat summary" terminology

**Problem:** The "chat summary" naming wrongly implies chat display is a primary output. In reality:
- **Primary**: `conforma-status-and-resolution-guide.md` → GitHub (comprehensive team reference)
- **Preview**: Chat display shows TODO-focused content for immediate action

**User feedback:** "TODO and resolution guide is the main goal of this output doc." The chat preview should contain TODO + metadata + violations breakdown — the actionable sections that tell users what to do.

## Proposed Architecture (after implementation)

```
┌──────────────────────────────────────────────────────────────────────┐
│ generate_resolution_guide.py                                          │
│                                                                        │
│  Orchestrator: assembles sections, writes both files                  │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Sections rendered (guide_renderers.py):                      │    │
│  │   1. todo = render_todo()                                    │    │
│  │   2. metadata = render_metadata_header()                     │    │
│  │   3. violations_breakdown = render_key_takeaways()           │    │
│  │   4. summary_metrics = render_summary()                      │    │
│  │   5. tooling_health = render_tooling_health()                │    │
│  │   6. coverage = render_coverage_table()                      │    │
│  │   7. resolution = render_resolution_guide()                  │    │
│  │   8. warnings = render_warnings_section()                    │    │
│  │   9. stats = render_statistical_breakdown()                  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                        │
│  if todo_file:                                                         │
│      write_todo_preview(todo_file,                                     │
│          todo, metadata_header, key_takeaways)                        │
│          ────────────────────────────────────┐                        │
│                                               │                        │
│  full_guide = join(all 9 sections)           │                        │
│      ────────────────────────────────────────┼──────┐                 │
│                                               │      │                 │
└───────────────────────────────────────────────┼──────┼─────────────────┘
                                                ▼      ▼
                         ┌───────────────────────────────────────────┐
                         │ Output Files                               │
                         ├───────────────────────────────────────────┤
                         │ conforma-todo.md (chat preview)            │
                         │   • TODO action items table                │
                         │   • Metadata header (context confirmation) │
                         │   • Violations Breakdown (5 tables)        │
                         ├───────────────────────────────────────────┤
                         │ conforma-resolution-guide.md (GitHub)      │
                         │   • All 9 sections (TODO through stats)    │
                         └───────────────────────────────────────────┘

context.yaml:
  steps.resolution_guide.guide_file: conforma-resolution-guide.md
  steps.resolution_guide.todo_file: conforma-todo.md
```

*Diagram is proposed in this document and reflects the implementation below.*

## Changes

### 1. Constants — `scripts/conforma_constants.py`
- Change `RESOLUTION_GUIDE_FILENAME` value to `"conforma-resolution-guide.md"`
- Add `TODO_PREVIEW_FILENAME = "conforma-todo.md"`

### 2. Rename function — `guide_renderers.py`
- `write_chat_summary()` → `write_todo_preview()`
- Remove `tooling_health`, `summary_metrics`, `guide_path`, `analysis_path` params
- Keep `todo`, `metadata_header`, `key_takeaways` params
- Remove "Detailed Documents" footer generation
- Update docstring and stderr message

### 3. Update generator — `generate_resolution_guide.py`
- Import rename: `write_chat_summary` → `write_todo_preview`, add `TODO_PREVIEW_FILENAME`
- Param rename: `chat_summary_file` → `todo_file`
- CLI flag: `--chat-summary-file` → `--todo-file`
- Default path: `chat-summary.md` → `TODO_PREVIEW_FILENAME`
- Context key: `chat_summary_file` → `todo_file`
- Variable renames: `cs_path` → `todo_path`
- Remove guide link backfill block (lines 597-608)
- Simplify call: only pass todo, metadata_header, key_takeaways

### 4. Workflow docs, SKILL.md, script-output-presentation.md
- All "chat summary" → "TODO" or "TODO preview"
- All `chat-summary.md` → `conforma-todo.md`
- All `conforma-status-and-resolution-guide.md` → `conforma-resolution-guide.md`

### 5. Tests
- Import/function rename: `write_chat_summary` → `write_todo_preview`
- Class renames: `TestChatSummary*` → `TestTodoPreview*`
- Param renames: `chat_summary_file=` → `todo_file=`
- File path refs: `chat-summary.md` → `TODO_PREVIEW_FILENAME`
- Context key: `chat_summary_file` → `todo_file`
- Remove tests for "Detailed Documents" and "Analysis Output" link
- Keep violation link tests (violations breakdown is still in TODO preview)

### 6. decompose_conforma.py
- `"write_chat_summary"` → `"write_todo_preview"`
- `"_write_chat_summary"` → `"_write_todo_preview"`

### 7. TODO.md
- Update item 15 ref, add item 23 with plan/jira/commit refs
