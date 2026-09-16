# R2 — Cross-model review checkpoint (end-to-end)

Status: **PENDING**
Plan: [`.agents/plans/conforma-analyze-jira-coverage-plan.md`](../../../.agents/plans/conforma-analyze-jira-coverage-plan.md) → Phase 5 DoD / Review checkpoint R2
Jira: [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)
Depends on: C11

## Goal

Independent cross-model review (manual `claude -p`, per confirmed decision 14) scoped to the finished feature: end-to-end integration, workflow determinism, and the live dry-run result from C11.

## Run

Same invocation shape as R1, with the prompt scope changed to "end-to-end integration, workflow determinism, and the live dry-run result". Suggested prompt:

```bash
claude -p --output-format json 'You are reviewing the finished in-repo implementation of the conforma-analyze Jira coverage feature. Focus ONLY on (a) end-to-end integration (discovery -> sync -> jira_sync.json -> guide renderers -> submit -> guide-URL comment), (b) workflow determinism (skills/conforma-analyze/workflows/full-analysis.md single-command steps), and (c) the live read-only dry-run result (find subcommand; RHOAIENG-70681 discovered as a prior issue, no writes). Read .agents/plans/conforma-analyze-jira-coverage-plan.md, scripts/conforma_jira_ticket_ops.py, skills/conforma-analyze/workflows/full-analysis.md, skills/conforma-analyze/scripts/guide_renderers.py, and their tests. Return a concise verdict: BLOCKING / NON-BLOCKING / PASS, then a numbered list of any blocking defects. Do not propose refactors beyond blocking defects.' > /tmp/review_r2.json
```

## Record

- Paste the `.result` field into the Handover section (§17) of the plan, under "Review R2".
- If verdict is BLOCKING: fix the listed defects, re-run C11 validation, then re-run this review.

## DoD

- Verdict recorded in the plan handover and is PASS or NON-BLOCKING (or blocking defects fixed + re-validated + re-reviewed).
- All items in [README.md](README.md) complete — this is the last gate on the plan.
