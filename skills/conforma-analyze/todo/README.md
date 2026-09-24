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
| [jira-column-manual-search.md](jira-column-manual-search.md) | Include manual Jira search guidance in TODO tables | NOT STARTED | Existing TODO Jira-column renderer |
| [exception-expiry-components-extra-args.md](exception-expiry-components-extra-args.md) | Show exception components and same-line extra arguments in expiry TODOs | NOT STARTED | Existing exception expiry extraction and TODO renderer |
| [move-generic-expiring-exceptions-to-warnings.md](move-generic-expiring-exceptions-to-warnings.md) | Move generic expiring exceptions from TODO/DONE into a warning section | NOT STARTED | Existing expiry renderer, section ledger, and presentation validator |
| [shared-policy-exception-matcher-variations.md](shared-policy-exception-matcher-variations.md) | Cover real current and historical policy exception formats in the shared matcher | NOT STARTED | Shared Conforma policy exception matcher plan |

## Execution order

```
R1 (checkpoint) → C12 → R2
C16 (independent)
```

Notes:

- The plan scheduled R1 after C7 (already done in `fe2aeaa`); its verdict was
  not recorded, so it remains the first pending checkpoint. Continue only if
  its verdict is PASS or NON-BLOCKING.
- C12 remains blocked on the completed C14 discovery contract; R2 remains the
  subsequent end-to-end review checkpoint.

## Follow-ups (not plan steps — tracked here so they are not lost)

- **Push branch** `skill/conforma` — the coverage work (`fe2aeaa` and earlier) is local only; nothing has been pushed.
- **Jira work-update comment** — no work-update comment has been posted to [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190) yet; run `/link-work-to-jira` after each commit.
- **Plan handover** — `.agents/plans/conforma-analyze-jira-coverage-plan.md` §17 records C14 as DONE; R1 and R2 remain pending review checkpoints.
