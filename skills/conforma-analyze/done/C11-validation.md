# C11 — Full validation + pre-commit coverage-gate wiring + live dry-run

Status: **DONE**
Plan: [`.agents/plans/conforma-analyze-jira-coverage-plan.md`](../../../.agents/plans/conforma-analyze-jira-coverage-plan.md) → Phase 5, Step 5.1
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
- Then run review checkpoint R2 — see [R2-cross-model-review.md](../todo/R2-cross-model-review.md).

## Results (2026-09-17)

- **Step 1 — unit suite:** `2597 passed, 5 skipped, 0 failed` (baseline was 2595 passed / 2 failed; the 2 failures were stale `patch(...)` targets broken by the ruff F401 cleanup that removed `import getpass`/`platform` from `create_jira_ticket.py` and `from datetime import` from `generate_resolution_guide.py`. Fixed by patching the real implementation modules: `jira_description_builders.getpass`/`platform` and `guide_renderers.datetime`).
- **Step 2 — coverage gate:** all four targets pass — `jira_ops.py` 98.1%, `conforma_constants.py` 100.0%, `conforma_jira_ops.py` 99.5%, `conforma_jira_ticket_ops.py` 98.3%.
- **Step 3 — pre-commit wiring:** `check-script-coverage` hook added to `.pre-commit-config.yaml`; `pre-commit run check-script-coverage --all-files` → **Passed**.
- **Step 4 — full pre-commit:** `pre-commit run --all-files` has **pre-existing out-of-scope debt** (lint/format on ~97 in-flight files in the working tree from the ruff cleanup, not part of this plan). The new hook itself passes. Recorded as a user-attention item rather than fixed here.
- **Step 5 — live dry validation:** `find` discovered **98 conforma tickets** (7 projects × 3 labels, all statuses), exit 0.
  - **DEFECT FOUND & FIXED:** the first `find` run performed **51 real self-heal label writes** (`+conforma`) despite the "read-only" contract — `find`'s `--dry-run` flag defaulted to write-on, contradicting the subcommand's documented read-only intent and this step's no-writes guard. Root-cause fix: `cmd_find` is now **unconditionally read-only** (self-heal belongs to `audit`/`repair`/`sync`); the misleading `--dry-run` flag was removed. Re-ran `find`: **98 tickets, 0 writes** (verified in `jira-find2.log`).
  - **DoD GAP (needs product decision):** RHOAIENG-70681 is **not** discoverable by the label-first design — live-verified `labels: []` on the ticket, and a direct label-JQL for that key returns 0 results. The plan's §4 assumption that the label-first cutover would surface 70681 as a prior issue does not hold for label-less tickets. Options (surface to user): (a) accept the gap and record it, (b) one-time self-heal of known prior issues (manual label on 70681), (c) add a keyword/text discovery pass (larger design change).
- **Step 6 — fixes from validation:** stale-patch test targets (Step 1) + `cmd_find` read-only fix (Step 5). Both re-validated with the full suite (Step 1) and the coverage gate (Step 2) after the fixes.

## Commit

- C11: pre-commit wiring + stale-patch test fixes + `cmd_find` read-only fix (see git log; message includes `Jira: RHAIENG-6190`).
- The uncommitted repo-wide ruff cleanup (97 files) is **out of scope** for C11 — tracked as a separate user-attention item (commit under RHAIENG-6190 or revert).
