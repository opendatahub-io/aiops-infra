# C8 — Cutover discovery (no shim)

Status: **NOT STARTED**
Plan: [`.agents/plans/conforma-analyze-jira-coverage-plan.md`](../../../.agents/plans/conforma-analyze-jira-coverage-plan.md) → Phase 4, Step 4.1
Jira: [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)
Depends on: `fe2aeaa` (Phase 3 done)

## Goal

Move Jira ticket discovery from the legacy 4-pass heuristic in `scripts/conforma_jira_ops.py` to the new label-first discovery in `scripts/conforma_jira_ticket_ops.py`, and repoint the coverage workflow at it. The old 4-pass is **removed, not shimmed** (repo rule: no backward-compatibility shims unless requested).

## Changes

- `scripts/conforma_jira_ops.py`
  - Remove the discovery body of `prefetch_open_jira_tickets` (line ~216) — the old 4-pass (label search, summary search, release filter, alias expansion).
  - `prefetch_open_jira_tickets` becomes a thin wrapper over `conforma_jira_ticket_ops.discover_conforma_tickets(...)` + `conforma_jira_ops.classify_ticket_version_relevance(...)`, **open-status-filtered** (the coverage table shows open tickets only).
  - KEEP `classify_ticket_version_relevance` (line ~193), `_normalize_version` (line ~188), `_extract_rule_from_summary`, `_extract_component_stems`, `_infer_rule_from_text` — still reused by the new script and the wrapper.
- `skills/conforma-analyze/scripts/violations_coverage.py`
  - The Jira prefetch lambda `_fetch_jira()` (line ~525) currently calls `conforma_jira_ops.prefetch_open_jira_tickets(...)` inside the parallel prefetch (MRs / Jira / Slack). After the cutover it must call the new label-first discovery path (open-filtered) and produce the same per-rule ticket structure the coverage table consumes (`key`, `url`, `matched_component_stem(s)`, etc.).
  - Update its unit tests if signatures change.
- `tests/unit/test_conforma_jira_ops.py`
  - Update/replace the 4-pass tests (pass-1 colon-suffix match, pass-2/3/4 branches added in the coverage work) to cover the new wrapper path; keep coverage of `classify_ticket_version_relevance` + version helpers.

## Grounding (verified against tree at `fe2aeaa`)

- `violations_coverage.py` parallel prefetch: `_fetch_mrs` / `_fetch_jira` / `_fetch_slack` (lines 512–564); Jira prefetch at line 525–528.
- `conforma_jira_ops.py` helper line numbers as listed above.
- `conforma_jira_ticket_ops.py` already exposes: `discover_conforma_tickets`, `match_violations`, `build_label_discovery_jql` (via `conforma_constants`), `classify` helpers imported from `conforma_jira_ops`.

## Verification

- `python -m pytest tests/unit/test_conforma_jira_ops.py tests/unit/test_conforma_analyze_violations_coverage.py tests/unit/test_conforma_analyze_violations_coverage_extended.py -q`
- `python tests/check_script_coverage.py` → all four targets still >97% (removing the 4-pass *shrinks* `conforma_jira_ops.py`; the wrapper + retained helpers must keep it covered).
- `ruff check` / `ruff format` clean on changed files.

## DoD

- Old 4-pass discovery deleted (no shim, no dead code path).
- Coverage workflow's Jira prefetch produces the same open-ticket table as before (open-status-filtered, release-relevance classified).
- All affected unit tests green; coverage gate green.
- Commit `C8` with message including `Jira: RHAIENG-6190 (https://redhat.atlassian.net/browse/RHAIENG-6190)`.
