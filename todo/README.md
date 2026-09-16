# Outstanding work — conforma-analyze Jira coverage

Jira: [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)
Plan: [`.agents/plans/conforma-analyze-jira-coverage-plan.md`](../.agents/plans/conforma-analyze-jira-coverage-plan.md)
One document per outstanding todo item. Status baseline: commit `fe2aeaa`, unit suite 2529 passed / 5 skipped, all four coverage-gated scripts >97%.

## Status at a glance

| Doc | Item | Status | Depends on |
|---|---|---|---|
| [C8-cutover-discovery.md](C8-cutover-discovery.md) | Cutover discovery (no shim) | NOT STARTED | `fe2aeaa` |
| [C9-renderer-changes.md](C9-renderer-changes.md) | Renderer: Jira block + JIRAs cell + per-row Jira col + pre-fill links | NOT STARTED | C8 |
| [C10-workflow-and-docs.md](C10-workflow-and-docs.md) | Workflow Step 8 + SKILL.md + search-conforma-jira-tickets + conforma/TODO.md | NOT STARTED | C9 |
| [C11-validation.md](C11-validation.md) | Full validation + pre-commit coverage-gate wiring + live read-only dry-run | NOT STARTED | C10 |
| [R1-cross-model-review.md](R1-cross-model-review.md) | Cross-model review checkpoint (Jira write correctness, TargetVersion, error surfacing) | PENDING (recorded in plan handover as PENDING) | C9, C10 |
| [R2-cross-model-review.md](R2-cross-model-review.md) | Cross-model review checkpoint (end-to-end integration, workflow determinism, live dry-run) | PENDING | C11 |

## Execution order

```
C8 → C9 → C10 → C11 → R2
              ↘ R1 (checkpoint; continue only if verdict PASS or NON-BLOCKING)
```

Notes:

- The plan scheduled R1 after C7 (already done in `fe2aeaa`); its verdict was not recorded, so it runs as a checkpoint before the Phase 4 work is considered complete. It does not gate C8.
- C11 is the only remaining code-touching step that changes `.pre-commit-config.yaml` (wires the per-script coverage gate). The gate is safe to wire only because all four targets are already >97%.
- The live dry-run in C11 is **read-only** (`find` subcommand only). Do NOT create real Jira tickets without explicit user confirmation.

## Follow-ups (not plan steps — tracked here so they are not lost)

- **Push branch** `skill/conforma` — the coverage work (`fe2aeaa` and earlier) is local only; nothing has been pushed.
- **Jira work-update comment** — no work-update comment has been posted to [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190) yet; run `/link-work-to-jira` after each commit.
- **Plan handover** — `.agents/plans/conforma-analyze-jira-coverage-plan.md` §17 still lists Phase 3 as NOT STARTED (stale) and R1/R2 as PENDING; update it as each item above lands.
