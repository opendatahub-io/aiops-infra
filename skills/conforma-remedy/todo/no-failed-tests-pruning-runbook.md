# `test.no_failed_tests` — route by the exact failed test task; complete the `fbc-target-index-pruning-check` runbook

Status: **NOT STARTED**
Origin: `rhoai-3.6-ea.1` Conforma report run (`~/.conforma/20260921T104043Z/`) — the uncovered violation `test.no_failed_tests` in `rhoai-fbc-fragment-v3-6-ea-1` turned out to be a `fbc-target-index-pruning-check` failure, whose resolution path is completely different from the generic "a test task failed" guidance.

## Goal

1. Make `conforma-remedy` state explicitly that `test.no_failed_tests` is a **family** of distinct failures: the exact failed test task named in the violation message determines the advised resolution path. Matching and presenting a remedy must never stop at the generic rule code.
2. Complete the runbook for the `fbc-target-index-pruning-check` failure type using the instructions below (polished; details kept intact).

## Current state

- `conforma-remedy` resolves violations through `skills/references/violation-catalog.yaml` (see `skills/conforma-remedy/SKILL.md` step 1 and `skills/conforma-remedy/scripts/match_violation.py` / `remedy_matchers.py`).
- The catalog already has two relevant entries:
  - `test.no_failed_tests` (generic, `skills/references/violation-catalog.yaml`) — its fix steps say to "identify which test task failed" and check the build logs, but they do **not** state that the failed-test value changes the resolution path, and they do not route to a task-specific entry.
  - `test.no_failed_tests.fbc_target_index_pruning` (`conforma_rule_codes: ["test.no_failed_tests:fbc-target-index-pruning-check"]`) — close to correct but incomplete; it lacks the `!FAILURE!` log-search procedure, the check-an-earlier-build fallback, the Slack thread context, and the preferred script.

## `fbc-target-index-pruning-check` — target runbook content

Violations of this type appear in the Conforma report as:

> The Task "fbc-target-index-pruning-check" from the build Pipeline reports a failed test

**Preferred process (as of July 2026):** run `generate-index-pruning-exception-list.sh` (created by Rishab Prasad) with the affected release tags — it **generates a new index pruning exception list** (the YAML exception entries with the container-image refs) that is then added to the self-service FBC exception file.

- The script is not committed in this repository or in `konflux-release-data`; obtain it from the [script thread](https://redhat-internal.slack.com/archives/C08UHLCPLQ6/p1776859237062819?thread_ts=1776856821.099939&cid=C08UHLCPLQ6) (or ask Rishab Prasad).
- The catalog/guide entry must reference the script **by name only** plus the thread link as its source — do not copy the script's contents or other Slack-thread content into the resolution guide.

**Diagnosis procedure:**

1. The Conforma report does not include — and does not give — details of the failed test itself. Identify the failure from the build logs instead.
2. Open the most recent **successful** build of the `rhoai-fbc-fragment` component in Konflux and inspect the logs of the `fbc-target-index-pruning-check` task.
3. If that log looks empty or too short, check the `fbc-target-index-pruning-check` logs in an **earlier** Konflux build of `rhoai-fbc-fragment` until the task log contains the failure details.
4. Search the log for lines containing:

   ```
   !FAILURE!
   ```

   Example:

   ```
   !FAILURE! - FBC fragment prunes rhods-operator.1.20.1-8 from rhods-operator.beta channel.
   ```

5. Such failures are often caused by a channel reset (e.g., a reset of the `beta` channel) — no troubleshooting of the component itself is required in that case. Prior context on this: [Slack thread](https://redhat-internal.slack.com/archives/C08UHLCPLQ6/p1773331066843919?thread_ts=1773330914.507779&cid=C08UHLCPLQ6).
6. **Confirm with Rishab Prasad** that the failure is caused by a channel reset.
7. **Resolution**: run the `generate-index-pruning-exception-list.sh` script with the affected release tags (see the preferred-process section above) and add its YAML output to the **self-service FBC exception file** (`$GITLAB_HOST/releng/konflux-release-data/-/blob/main/exceptions/fbc-rhoai-prod.yaml`) via a GitLab Merge Request. The script output **replaces** the manual per-OCP-version `skopeo inspect` digest lookup that the current catalog entry describes. The exception itself still follows the self-service workflow documented in `skills/conforma-exception/workflows/create.md` (RHOAIENG Senior Management approval ticket → Approval Gate → Merge Request to `exceptions/`); the script only automates the image-ref collection step.

## Scope

1. **Generic entry** (`test.no_failed_tests` in `skills/references/violation-catalog.yaml`): add a `triage_note` and a leading fix step stating that the **failed test task name in the violation message selects the resolution path** — match it against the task-specific catalog entries (e.g., `test.no_failed_tests:fbc-target-index-pruning-check`) and the known false alerts before falling back to the generic procedure.
2. **Pruning entry** (`test.no_failed_tests.fbc_target_index_pruning`): update `triage_note`, `description`, and `fix_steps` to carry the polished runbook above, including:
   - the preferred script (`generate-index-pruning-exception-list.sh`, run with the affected release tags) with the [Slack script thread](https://redhat-internal.slack.com/archives/C08UHLCPLQ6/p1776859237062819?thread_ts=1776856821.099939&cid=C08UHLCPLQ6) as its source — script name and link only, no script internals or Slack content in the entry,
   - the `!FAILURE!` log search with the example line,
   - the "most recent successful build, fall back to an earlier build if the log is empty/short" step,
   - the channel-reset (EA drop / separate EA Index pending) context with both Slack thread permalinks,
   - the confirmation step with Rishab Prasad,
   - the resolution step: script output added to the self-service FBC exception file via Merge Request, per `skills/conforma-exception/workflows/create.md` (this replaces the manual `skopeo inspect` digest lookup the current entry describes).
3. **`skills/conforma-remedy/SKILL.md`**: in the "Identify the violation" step, add an explicit note for family rule codes (`test.no_failed_tests` and similar) that matching must continue to the most specific task-scoped entry — the generic code alone is not the remedy.
4. **Tests**: extend `tests/unit/test_conforma_remedy_match_violation.py` so a `test.no_failed_tests` query naming the pruning task resolves to `test.no_failed_tests.fbc_target_index_pruning`, and a `test.no_failed_tests` query naming an unknown task resolves to the generic entry.

## DoD

- A `conforma-remedy` lookup of "The Task \"fbc-target-index-pruning-check\" from the build Pipeline reports a failed test" presents the pruning-specific runbook (preferred script, `!FAILURE!` search, channel-reset confirmation with Rishab Prasad), not the generic test-failure guidance.
- `test.no_failed_tests` violations naming any other failed task still resolve to the generic entry (plus the applicable known false alert, e.g., `fbc_no_failed_tests_push`).
- The catalog entry, the SKILL.md routing note, and the unit tests are all in place; `pytest tests/unit/test_conforma_remedy_match_violation.py -q` passes.

## References

- Violation catalog: [skills/references/violation-catalog.yaml](../../references/violation-catalog.yaml)
- Existing pruning entry: `test.no_failed_tests.fbc_target_index_pruning` in the catalog
- Self-service FBC exception file: `$GITLAB_HOST/releng/konflux-release-data/-/blob/main/exceptions/fbc-rhoai-prod.yaml`
- Self-service exception workflow: `skills/conforma-exception/workflows/create.md` (`test.no_failed_tests:fbc-target-index-pruning-check` is a self-service rule)
- Prior Slack context (beta channel / EA resets): [C08UHLCPLQ6 thread, 2026-03-12](https://redhat-internal.slack.com/archives/C08UHLCPLQ6/p1773331066843919?thread_ts=1773330914.507779&cid=C08UHLCPLQ6)
- Pruning script thread (source of `generate-index-pruning-exception-list.sh`, Rishab Prasad): [C08UHLCPLQ6 thread](https://redhat-internal.slack.com/archives/C08UHLCPLQ6/p1776859237062819?thread_ts=1776856821.099939&cid=C08UHLCPLQ6)
