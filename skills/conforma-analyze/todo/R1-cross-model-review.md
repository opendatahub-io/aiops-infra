# R1 — Cross-model review checkpoint (ticket ops)

Status: **PENDING** (recorded as PENDING in the plan handover §17; its scheduled slot was "after C7" — C7 already landed in `fe2aeaa`, the verdict was never recorded)
Plan: [`.agents/plans/conforma-analyze-jira-coverage-plan.md`](../../../.agents/plans/conforma-analyze-jira-coverage-plan.md) → Phase 3 DoD / Review checkpoint R1
Jira: [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)
Depends on: C9 + C10 (run once the Phase 4 diff is final so the reviewer sees the whole feature; the checkpoint does **not** gate C8)

## Goal

Independent cross-model review (manual `claude -p`, per confirmed decision 14 — no automation) of the Jira write path. **Continue only if verdict is PASS or NON-BLOCKING**; blocking defects must be fixed and the review re-run.

## Run

```bash
claude -p --output-format json 'You are reviewing an in-repo implementation plan and its diff for the conforma-analyze Jira coverage feature. Focus ONLY on (a) Jira write correctness, (b) deterministic error surfacing (no silent empty results), (c) the TargetVersion (customfield_10855) handling, and (d) test adequacy. Read .agents/plans/conforma-analyze-jira-coverage-plan.md, scripts/conforma_jira_ticket_ops.py, scripts/jira_ops.py, and their tests. Return a concise verdict: BLOCKING / NON-BLOCKING / PASS, then a numbered list of any blocking defects. Do not propose refactors beyond blocking defects.' > /tmp/review_r1.json
```

## Record

- Paste the `.result` field into the Handover section (§17) of the plan, under "Review R1".
- If verdict is BLOCKING: fix the listed defects (new commit under [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)), then re-run the review.

## DoD

- Verdict recorded in the plan handover and is PASS or NON-BLOCKING (or blocking defects fixed + re-reviewed).
