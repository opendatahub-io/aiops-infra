# Outstanding work — conforma-analyze Jira coverage

Jira: [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)
Plan: [`.agents/plans/conforma-analyze-jira-coverage-plan.md`](../../../.agents/plans/conforma-analyze-jira-coverage-plan.md)
Completed work is archived in [done/README.md](../done/README.md). This index
contains only active and outstanding work.

## Status at a glance

| Doc | Item | Status | Depends on |
|---|---|---|---|
| [R1-cross-model-review.md](R1-cross-model-review.md) | Cross-model review checkpoint (Jira write correctness, TargetVersion, error surfacing) | PENDING (recorded in plan handover as PENDING) | C9, C10 |
| [R2-cross-model-review.md](R2-cross-model-review.md) | Cross-model review checkpoint (end-to-end integration, workflow determinism, live dry-run) | PENDING | C11 |
| [C12-default-jira-creation.md](C12-default-jira-creation.md) | Enable Jira ticket creation by default | NOT STARTED | C14 (DONE) |
| [C16-model-provenance-in-resolution-guide.md](C16-model-provenance-in-resolution-guide.md) | Include model name and version in the resolution guide metadata | NOT STARTED | Existing `ai_model` context handling |

## Execution order

```
C9 → C10 → C11 → C13 → C14 → C12 → R2
                   ↘ C14 feeds broader candidates back into C13 labelling
        ↘ R1 (checkpoint; continue only if verdict PASS or NON-BLOCKING)
```

Notes:

- The plan scheduled R1 after C7 (already done in `fe2aeaa`); its verdict was not recorded, so it runs as a checkpoint before the Phase 4 work is considered complete. It does not gate C8.
- C11 is the only remaining code-touching step that changes `.pre-commit-config.yaml` (wires the per-script coverage gate). The gate is safe to wire only because all four targets are already >97%.
- The C14 live acceptance was **read-only**: `find` returned 98 tickets, and
  the targeted `audit-ticket` command confirmed RHOAIENG-70681 without
  applying labels. Do NOT create real Jira tickets or apply labels without
  explicit user confirmation.

## Follow-ups (not plan steps — tracked here so they are not lost)

- **Push branch** `skill/conforma` — the coverage work (`fe2aeaa` and earlier) is local only; nothing has been pushed.
- **Jira work-update comment** — no work-update comment has been posted to [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190) yet; run `/link-work-to-jira` after each commit.
- **Plan handover** — `.agents/plans/conforma-analyze-jira-coverage-plan.md` §17 records C14 as DONE; R1 and R2 remain pending review checkpoints.
- **C14 acceptance record** — archived in
  [done/C14-hybrid-jira-relatedness-discovery.md](../done/C14-hybrid-jira-relatedness-discovery.md),
  including the live RHOAIENG-70681 evidence and the explicit structured-field
  limitations.
