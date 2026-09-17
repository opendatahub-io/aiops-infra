# C10 — Workflow Step 8 (Jira Sync) + docs

Status: **DONE**
Plan: [`.agents/plans/conforma-analyze-jira-coverage-plan.md`](../../../.agents/plans/conforma-analyze-jira-coverage-plan.md) → Phase 4, Step 4.3
Jira: [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)
Depends on: C9

## Goal

Wire the Jira sync step into the conforma-analyze workflow and update the skill docs that describe capabilities and ticket discovery.

## Changes

- `skills/conforma-analyze/workflows/full-analysis.md` (234 lines today; numbered steps 1–10)
  - New **Step 8 "Jira Sync"** between coverage (step 7) and the resolution-guide step. Command (single deterministic form — no conditional variants, per `check_workflow_determinism`):
    `~/.conforma/bin/conforma_run.sh scripts/conforma_jira_ticket_ops.py create-jiras-for-conforma-violations`
  - Renumber existing steps: 8 (Resolution Guide) → 9, 9 (Generate the resolution guide) → 10, 10 (Submit to GitHub) → 11.
  - Update all cross-references that mention the old step numbers: the "TODO preview in step 9" note in step 6 (line ~144), the "See step 9 for the generation command" note in the Resolution Guide step (line ~183), the "requires user confirmation … separate turn after step 9" note in Submit (line ~219), and the hard-failure rule cross-references to steps 9/10.
- `skills/conforma-analyze/SKILL.md`
  - Add the Jira-sync capability to the capability/routing table.
- `skills/search-conforma-jira-tickets/SKILL.md`
  - Delegate to the new label-first discovery (`scripts/conforma_jira_ticket_ops.py find`) instead of the removed 4-pass.
- `skills/conforma/TODO.md`
  - Mark item 11 (line 29: "ensure the jira coverage can find closed jiras as well … RHOAIENG-70681 should be found for …") done, with a link to this plan and [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190). Follow the existing "~~item~~ — done. Jira: …" style used by items 20–31.

## Verification

- `python tests/check_workflow_determinism.py` — the new step must be a single deterministic command (no "run X, or if … run Y").
- `python tests/check_path_references.py` — new/changed markdown links must resolve.
- `python -m pytest tests/unit/test_check_workflow_determinism.py -q`

## DoD

- Workflow has Step 8 "Jira Sync"; old 8/9/10 renumbered to 9/10/11 with all cross-references updated (no dangling "step N" references).
- SKILL.md capability table, search-conforma-jira-tickets, and conforma/TODO.md item 11 updated.
- Workflow-determinism + path-reference checks green.
- Commit `C10` with message including `Jira: RHAIENG-6190 (https://redhat.atlassian.net/browse/RHAIENG-6190)`.
