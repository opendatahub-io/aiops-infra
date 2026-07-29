# Plan: Fix Guide Filename Resolution + TODO as Primary Output

**Jira**: [RHAIENG-6190](https://redhat.atlassian.net/browse/RHAIENG-6190)  
**Builds on**: `skills/conforma-analyze/.plans/add-todo-section-to-executive-summary.md`  
**TODO.md items addressed**: #20 (extend), #22 (remove executive summary wording)

## Problem Statement

Two bugs found during a conforma report run for rhoai-3.5:

1. **guide.md filename mismatch**: `submit_resolution_guide.py` resolves the guide path by reading `steps.resolution_guide.guide_file` from context.yaml. If that value is stale or wrong (observed: `guide.md` instead of `conforma-status-and-resolution-guide.md`), submission fails with "Guide file not found". The canonical filename is hardcoded separately in 3 scripts with no shared constant.

2. **TODO missing from full guide**: `render_todo()` output only appears in the chat-display file (`executive-summary.md`). The full resolution guide (submitted to GitHub) starts with the metadata table — no TODO. The TODO action table should be the first section of both the chat output AND the submitted guide.

3. **"Executive summary" terminology**: The concept, function names, file names, CLI flags, context.yaml keys, and doc references all use "executive summary". This should be renamed to "chat summary" throughout (full rename — functions, params, context keys, file name).

## Proposed Architecture (after implementation)

```
                ┌──────────────────────────────────────────────┐
                │ conforma_constants.py                         │
                │   RESOLUTION_GUIDE_FILENAME = "conforma-..."  │◄── NEW: single source of truth
                └──────────────┬───────────────────────────────┘
                               │ imported by
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
┌────────────────┐  ┌───────────────────┐  ┌────────────────────┐
│ generate_       │  │ submit_            │  │ validate_           │
│ resolution_     │  │ resolution_        │  │ guide_links.py      │
│ guide.py        │  │ guide.py           │  │                     │
│                 │  │                    │  │ find_latest_guide() │
│ L469: uses      │  │ L33: DEFAULT_      │  │ L212: glob pattern  │
│ constant for    │  │ FILENAME from      │  │ from constant       │
│ default output  │  │ constant           │  │                     │
│                 │  │                    │  │ L254: canonical     │
│ L279: sections  │  │ L261-268: resolve  │  │ path first, then   │
│ now includes    │  │ guide path:        │  │ context.yaml        │
│ todo as first   │  │ 1. run_dir/const   │  │ fallback            │
│ element         │  │ 2. context.yaml    │  └────────────────────┘
│                 │  │ 3. CLI arg         │
│ L474: uses      │  └───────────────────┘
│ "chat-summary   │
│ .md" default    │
│ (renamed)       │
└────────┬────────┘
         │ calls
         ▼
┌────────────────────────────────────────────┐
│ guide_renderers.py                          │
│                                             │
│ write_chat_summary()  ◄── RENAMED from      │
│                          write_executive_    │
│                          summary()           │
│                                             │
│ Output file: chat-summary.md  ◄── RENAMED   │
│                                             │
│ Section order:                              │
│   1. todo          (shown in agent chat)    │
│   2. metadata_header                        │
│   3. key_takeaways (Violations Breakdown)   │
│   4. tooling_health                         │
│   5. summary_metrics                        │
│   6. detailed_documents (file links)        │
└─────────────────────────────────────────────┘

Full resolution guide (submitted to GitHub):
  1. todo                    ◄── NEW (first section)
  2. metadata_header
  3. key_takeaways (Violations Breakdown)
  4. summary_metrics
  5. tooling_health
  6. violations_coverage     (kept for now)
  7. resolution_guide
  8. statistical_breakdown

Chat display (shown in agent response):
  = contents of chat-summary.md, rendered verbatim
  = TODO + metadata + Violations Breakdown + tooling + summary + links

context.yaml keys:
  steps.resolution_guide.guide_file          (unchanged)
  steps.resolution_guide.chat_summary_file   ◄── RENAMED from executive_summary_file
```

*Diagram is proposed in this document and reflects the implementation below.*

## Changes

### 1. Add shared constant — `scripts/conforma_constants.py`

Add after `WARNINGS_CSV_FILENAME` (line 13):

```python
RESOLUTION_GUIDE_FILENAME = "conforma-status-and-resolution-guide.md"
```

All 3 scripts that reference this filename will import and use it instead of hardcoding.

### 2. Deterministic guide path — `submit_resolution_guide.py`

**Import** (add to line 30 imports):
```python
from conforma_constants import RESOLUTION_GUIDE_FILENAME
```

**Replace** line 33:
```python
DEFAULT_FILENAME = RESOLUTION_GUIDE_FILENAME
```

**Change guide file resolution** (lines 261-268). New logic:
1. Use `--guide-file` CLI arg if provided
2. Try canonical path: `run_dir / RESOLUTION_GUIDE_FILENAME` — if file exists, use it
3. Fall back to context.yaml `steps.resolution_guide.guide_file` — for non-standard names
4. Error if none found

```python
guide_file = args.guide_file
if guide_file is None and run_dir:
    canonical = Path(run_dir) / RESOLUTION_GUIDE_FILENAME
    if canonical.exists():
        guide_file = str(canonical)
    elif context:
        ctx_guide = conforma_context_ops.get(run_dir, "steps.resolution_guide.guide_file", None)
        if ctx_guide:
            guide_file = str(Path(run_dir) / ctx_guide)
if guide_file is None:
    print("Error: --guide-file is required when no run context is available", file=sys.stderr)
    return 1
```

### 3. Use constant in generate — `generate_resolution_guide.py`

**Import** (add to line 30-area imports, near existing `conforma_constants` import if any — check with autodiscovery):
```python
from conforma_constants import RESOLUTION_GUIDE_FILENAME
```

**Replace** line 469 hardcoded string:
```python
output_file = str(Path(run_dir) / RESOLUTION_GUIDE_FILENAME)
```

### 4. Use constant in validate — `validate_guide_links.py`

**Import** `RESOLUTION_GUIDE_FILENAME` and use it at line 212:
```python
pattern = os.path.join(work_dir, "*", RESOLUTION_GUIDE_FILENAME)
```

And at line 254-256, add canonical-path-first logic (same pattern as submit):
```python
if run_dir:
    canonical = Path(run_dir) / RESOLUTION_GUIDE_FILENAME
    if canonical.exists():
        guide_file = str(canonical)
    else:
        ctx_guide = conforma_context_ops.get(run_dir, "steps.resolution_guide.guide_file", None)
        if ctx_guide:
            guide_file = str(Path(run_dir) / ctx_guide)
        else:
            print(json.dumps({"error": "No guide_file in context ...", "all_ok": False}))
            return 1
```

### 5. Add TODO to full guide sections — `generate_resolution_guide.py`

At line 279, prepend `todo` to the `sections` list:

```python
sections = [
    todo,                    # ← NEW: first section
    metadata_header,
    key_takeaways,
    summary_metrics,
    tooling_health,
    _render_coverage_table(coverage_data),
    _render_resolution_guide(...),
    _render_warnings_section(...),
    _render_statistical_breakdown(...),
]
```

### 6. Full rename: executive_summary → chat_summary

#### 6a. `guide_renderers.py`

| Line | Old | New |
|------|-----|-----|
| 1337 | `def write_executive_summary(` | `def write_chat_summary(` |
| 1348 | docstring: `executive summary` | `chat summary` |
| 1372 | `Executive summary written to` | `Chat summary written to` |
| 378 | docstring: `executive summary` | `chat summary` |

#### 6b. `generate_resolution_guide.py`

| Line | Old | New |
|------|-----|-----|
| 57 | `from guide_renderers import write_executive_summary as _write_executive_summary` | `from guide_renderers import write_chat_summary as _write_chat_summary` |
| 58 | `from guide_renderers import render_todo as _render_todo` | (unchanged) |
| 202 | `executive_summary_file: str \| None = None,` | `chat_summary_file: str \| None = None,` |
| 211-215 | docstring refs to `executive_summary_file` | update to `chat_summary_file` |
| 292-294 | `if executive_summary_file: _write_executive_summary(executive_summary_file,` | `if chat_summary_file: _write_chat_summary(chat_summary_file,` |
| 413 | `"--executive-summary-file"` | `"--chat-summary-file"` |
| 415 | help text: `executive summary` | `chat summary` |
| 474-476 | `executive_summary_file = args.executive_summary_file` / `"executive-summary.md"` | `chat_summary_file = args.chat_summary_file` / `"chat-summary.md"` |
| 579 | `executive_summary_file=executive_summary_file,` | `chat_summary_file=chat_summary_file,` |
| 595-596 | `if executive_summary_file: es_path = ...` | `if chat_summary_file: cs_path = ...` |
| 612-613 | `step_outputs["executive_summary_file"]` | `step_outputs["chat_summary_file"]` |
| 5 | Public API docstring | Update param name |

#### 6c. Context.yaml key

The context.yaml step output key changes from `steps.resolution_guide.executive_summary_file` to `steps.resolution_guide.chat_summary_file`. This is written by `generate_resolution_guide.py` (line 613) and read by the workflow step 9 agent instruction.

**Note**: No migration needed — context.yaml is per-run (ephemeral), not persistent config. Old runs keep old keys; new runs get new keys.

### 7. Update workflow docs — `workflows/full-analysis.md`

All instances of "executive summary" → "chat summary". All instances of `executive-summary.md` → `chat-summary.md`. Key changes:

- Step 6 (line 144): "the chat summary in step 9 covers the key data"
- Step 8 (line 183): "Only the **chat summary** is presented in the chat"
- Step 9 rule headings: "CHAT SUMMARY ONLY", "RULE 1 — CHAT SUMMARY ONLY"
- Step 9 (line 198): "read `chat-summary.md` from the active run directory"
- Step 9 (line 191): "output paths (guide file, chat summary file)"
- Step 9-10 transition references
- Bash description in step 9: keep as `"Generate Conforma Status and Resolution Guide"` (unchanged — it's the guide generator, not the chat summary)

### 8. Update other docs

#### `skills/conforma-analyze/SKILL.md` (line 105)
- "All chat summary, analysis, and resolution guide metrics MUST use violation counts"

#### `skills/references/script-output-presentation.md`
- All "executive summary" → "chat summary"  
- `executive-summary.md` → `chat-summary.md`
- `--executive-summary-file` → `--chat-summary-file`

#### `.claude/skills/conforma/SKILL.md` (line 75)
- Already says "Violations Breakdown" not "Executive Summary" — no change needed

### 9. Update TODO.md

Add completion entry for this work with plan file reference, jira link, and commit hash (filled in after commit).

### 10. Unit tests

#### New tests to add:

**In `test_conforma_analyze_submit_resolution_guide.py`:**
- `test_resolves_guide_from_canonical_filename`: Create run dir with `conforma-status-and-resolution-guide.md` but set context.yaml `guide_file` to `wrong-name.md`. Verify submit finds the canonical file, not the context value.
- `test_falls_back_to_context_when_canonical_missing`: Create run dir with `custom-guide.md`, set context.yaml `guide_file` to `custom-guide.md`, no canonical file. Verify submit uses context fallback.

**In `test_conforma_analyze_generate_resolution_guide.py`:**
- `test_todo_appears_in_full_guide`: Call `generate_resolution_guide()` and verify `## TODO` appears in the returned content (the full guide string), before `# Conforma Status`.
- `test_chat_summary_written_when_flag_provided`: Same as existing `test_executive_summary_written_when_flag_provided` but with renamed function/file. Verify `chat-summary.md` is created.
- `test_chat_summary_contains_todo`: Verify the chat summary file starts with the TODO section.

#### Existing tests to update:

- `TestExecutiveSummaryFile` class (5 tests): rename to `TestChatSummaryFile`, update file path references from `executive-summary.md` to `chat-summary.md`, update function call from `write_executive_summary` to `write_chat_summary`.
- `TestExecutiveSummaryViolationLinks` class (2 tests): rename to `TestChatSummaryViolationLinks`.
- `TestExecutiveSummaryTodoSection` class (3 tests): rename to `TestChatSummaryTodoSection`.
- `TestFullGuideUnchangedWithExecutiveSummaryFlag` test: rename, verify full guide now includes TODO.
- `TestContextIntegration` tests that reference `executive_summary_file` in step outputs: update key name.
- Any stderr assertion checking for `"Executive summary written to"` → `"Chat summary written to"`.

#### Constant test:

**In `test_conforma_constants.py` (or inline):**
- `test_resolution_guide_filename_constant_matches_generate_default`: Import `RESOLUTION_GUIDE_FILENAME`, verify it equals `"conforma-status-and-resolution-guide.md"`.

### 11. Autodiscovery of affected files

Before implementation, run these commands to find ALL references (do NOT use static lists — autodiscover):

```bash
# Find all files referencing the old naming
grep -rn 'executive.summary\|executive_summary\|executive-summary' \
  skills/conforma-analyze/ skills/references/ .claude/skills/conforma/ \
  tests/unit/test_conforma_analyze_* scripts/conforma_constants.py \
  --include='*.py' --include='*.md' --include='*.yaml' 2>/dev/null \
  | grep -v __pycache__ | grep -v '.plans/'

# Find all hardcoded guide filename references
grep -rn 'conforma-status-and-resolution-guide' \
  skills/ scripts/ tests/ --include='*.py' --include='*.md' 2>/dev/null \
  | grep -v __pycache__ | grep -v '.plans/'
```

Use the output to verify every reference is covered. If any reference is found outside the files listed above, add it to the change set.

## Files touched (autodiscovered — verify with grep commands above)

| File | Change type |
|------|-------------|
| `scripts/conforma_constants.py` | Add `RESOLUTION_GUIDE_FILENAME` |
| `skills/conforma-analyze/scripts/generate_resolution_guide.py` | Import constant, use it, add TODO to sections, full rename executive→chat |
| `skills/conforma-analyze/scripts/guide_renderers.py` | Rename function + user-facing strings |
| `skills/conforma-analyze/scripts/submit_resolution_guide.py` | Import constant, deterministic path resolution |
| `skills/conforma-analyze/scripts/validate_guide_links.py` | Import constant, canonical-path-first resolution |
| `skills/conforma-analyze/workflows/full-analysis.md` | Rename all executive summary → chat summary |
| `skills/conforma-analyze/SKILL.md` | Rename in line 105 |
| `skills/references/script-output-presentation.md` | Rename terminology |
| `skills/conforma/TODO.md` | Add completion entry |
| `tests/unit/test_conforma_analyze_generate_resolution_guide.py` | Rename classes/tests, add new tests, update assertions |
| `tests/unit/test_conforma_analyze_submit_resolution_guide.py` | Add canonical-path tests, update context key refs |

## Verification

```bash
# 1. Run affected tests
pytest tests/unit/test_conforma_analyze_generate_resolution_guide.py \
       tests/unit/test_conforma_analyze_submit_resolution_guide.py \
       tests/unit/test_conforma_context_ops.py \
       -x -v

# 2. Verify no remaining "executive summary" in user-facing output
grep -rn 'executive.summary\|executive_summary\|executive-summary' \
  skills/ scripts/ --include='*.py' --include='*.md' 2>/dev/null \
  | grep -v __pycache__ | grep -v '.plans/' | grep -v 'test_'
# Expected: 0 results

# 3. Verify constant is used consistently
grep -rn 'conforma-status-and-resolution-guide' \
  skills/ scripts/ --include='*.py' 2>/dev/null \
  | grep -v __pycache__ | grep -v '.plans/' | grep -v 'test_'
# Expected: only conforma_constants.py

# 4. Dry-run the full workflow
# conforma report for rhoai-3.5
```

## Not in scope (deferred)

- Removing Violations Coverage section from full guide (TODO.md #15 — deferred per user)
- Product-agnostic config (TODO.md #6)
- Splitting large Python modules (TODO.md #7)
- Live workflow verification (TODO.md #5)
