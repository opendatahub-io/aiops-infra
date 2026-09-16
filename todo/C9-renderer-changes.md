# C9 — Renderer: Jira block, JIRAs cell, per-row Jira column, pre-fill links

Status: **NOT STARTED**
Plan: [`.agents/plans/conforma-analyze-jira-coverage-plan.md`](../.agents/plans/conforma-analyze-jira-coverage-plan.md) → Phase 4, Step 4.2
Jira: [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)
Depends on: C8

## Goal

Make the resolution guide surface Jira state everywhere: per-violation **Jira tickets** block, extended **JIRAs** cell in the components table, a per-row **Jira** column in the numbered TODO tables, and `Create Jira ticket` pre-fill links for component groups without an open ticket.

## Changes

- `skills/conforma-analyze/scripts/generate_resolution_guide.py`
  - Read `jira_sync.json` from the active run directory. **Absent file ⇒ graceful fallback to current behavior** (no error, no empty sections).
  - Pass the parsed sync data to the renderers.
  - After **successful** guide submission only: call `conforma_jira_ticket_ops.add_guide_url_comment(created_keys, guide_url)` (non-blocking — a comment failure is reported, never fails the workflow).
- `skills/conforma-analyze/scripts/guide_renderers.py`
  - Per-violation section: new **Jira tickets** block — open tickets with status + release relevance; prior issues (closed, non-blocking); created-this-run tickets; one `Create Jira ticket` pre-fill link per component group with no open ticket.
  - `render_components_table` (line ~1344) JIRAs cell: currently built from `violation.get("open_jira_tickets", [])` with stem matching (lines 1381–1466); extend with created tickets + pre-fill links.
  - Numbered TODO tables: new per-row **Jira** column — ticket key(s) if found/created, else the `Create` pre-fill link.

## Tests

- `tests/unit/test_conforma_analyze_generate_resolution_guide.py`:
  - Jira block rendered (open + prior + created + pre-fill link).
  - JIRAs cell extended with created tickets + pre-fill links.
  - Per-row Jira column populated / falls back to `Create` link.
  - Absent `jira_sync.json` → exact current output (fallback).
  - Guide-URL comment called **only** on successful submit; comment error does not fail generation/submit.

## Verification

- `python -m pytest tests/unit/test_conforma_analyze_generate_resolution_guide.py -q`
- `python tests/check_workflow_determinism.py` and `python tests/check_path_references.py` (docs unchanged yet, but cheap to confirm).
- `ruff check` / `ruff format` clean.

## DoD

- Renderer shows Jira everywhere (block, cell, per-row column, pre-fill links) driven purely by `jira_sync.json`.
- Absent-file fallback is byte-identical to today's guide for the non-Jira sections.
- Guide-URL comment is wired, non-blocking, and submit-only.
- All affected unit tests green.
- Commit `C9` with message including `Jira: RHAIENG-6190 (https://redhat.atlassian.net/browse/RHAIENG-6190)`.
