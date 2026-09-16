# C11 — Full validation + pre-commit coverage-gate wiring + live dry-run

Status: **NOT STARTED**
Plan: [`.agents/plans/conforma-analyze-jira-coverage-plan.md`](../.agents/plans/conforma-analyze-jira-coverage-plan.md) → Phase 5, Step 5.1
Jira: [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)
Depends on: C10

## Goal

End-to-end validation, wire the per-script >97% coverage gate into pre-commit (deferred since C4, when wiring it would have blocked C5–C10), and prove live discovery finds the closed prior-issue ticket.

## Steps

1. **Full unit suite** — `python -m pytest tests/unit/ -q`. Must be ≥ 2366 passing, 0 failing (baseline at C4; suite is already 2529 passed / 5 skipped at `fe2aeaa`, so this is a regression check after C8–C10).
2. **Coverage gate** — `python tests/check_script_coverage.py`. All four plan-touched scripts >97%: `scripts/conforma_constants.py`, `scripts/jira_ops.py`, `scripts/conforma_jira_ops.py`, `scripts/conforma_jira_ticket_ops.py`. At `fe2aeaa`: 100.0 / 98.1 / 99.1 / 98.3 — C8's cutover (shrinks `conforma_jira_ops.py`) may move the last one; re-check.
3. **Wire the gate into pre-commit** — add to `.pre-commit-config.yaml` (currently NOT wired; verified):
   ```yaml
   - id: check-script-coverage
     name: per-script coverage >97% for plan-touched scripts
     entry: python tests/check_script_coverage.py
     language: system
     pass_filenames: false
     always_run: true
   ```
   Safe to wire only now, because all four targets are >97%.
4. **Full pre-commit** — `pre-commit run --all-files`. All hooks green, including the new `check-script-coverage` hook.
5. **Live dry validation (READ-ONLY)** — on the active run (`~/.conforma/.conforma-active/`, rhoai-3.6-ea.2, prod; Jira auth verified):
   - Run `~/.conforma/bin/conforma_run.sh scripts/conforma_jira_ticket_ops.py find` (discovery only, **no writes**).
   - Confirm **RHOAIENG-70681** (closed, Bug, no `conforma-violation` label) is found as a prior issue.
   - **Do NOT create real Jira tickets** (user guard — explicit confirmation required for any write).
6. Fix anything the validation surfaces (each fix re-runs steps 1–4).

## DoD

- Full unit suite green (≥ baseline), per-script coverage >97% on all four targets, `pre-commit run --all-files` clean, live `find` confirms RHOAIENG-70681 discovered.
- Commit `C11` (pre-commit wiring + any fixes from validation) with message including `Jira: RHAIENG-6190 (https://redhat.atlassian.net/browse/RHAIENG-6190)`.
- Then run review checkpoint R2 — see [R2-cross-model-review.md](R2-cross-model-review.md).
