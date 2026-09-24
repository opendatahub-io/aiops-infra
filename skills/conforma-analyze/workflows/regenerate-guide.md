## References (load these before executing)

No additional references needed.

---

# Regenerate Guide Workflow

## Regenerate Resolution Guide

Re-render the resolution guide and TODO/DONE/WARNINGS preview for the **active conforma run** (the target of the `~/.conforma/.conforma-active` symlink) from the data already present in its run directory. No data is fetched and no inputs are re-analyzed — only the guide rendering is repeated. Use this when the user asks anything like:
- "Regenerate the resolution guide"
- "Rerun the resolution guide for the most recent (active) run"
- "Refresh the guide with the latest rendering logic"
- "Re-render the guide/TODO/DONE preview"

The run to act on is always the **active run** — resolved by `~/.conforma/bin/conforma_run.sh` via the `.conforma-active` symlink. Never ask the user which run, which release, or where the files live, and never pass `--release`, `--run-dir`, `--coverage-json`, or output paths as CLI arguments: the script reads all inputs (violations YAML, coverage JSON, CSVs, tooling health, metadata) and output paths from the active run's `context.yaml`.

**Do NOT use this workflow** to re-fetch data, re-run coverage, or analyze a new release — those require the full analysis workflow (`workflows/full-analysis.md`). This workflow is rendering-only.

### Precondition

The active run must already contain completed inputs. If the `.conforma-active` symlink is missing or the run's `context.yaml` lacks a `steps.resolution_guide` entry (i.e. the guide has never been generated for that run), stop and tell the user to run the full analysis workflow for that release instead. Do not start a new run from this workflow.

### Steps

**Script path convention**: Use `~/.conforma/bin/conforma_run.sh` to resolve the aiops-infra repo root and dispatch to the target Python script. Do NOT use bare `python3` paths — always use the wrapper.

1. **Regenerate the resolution guide**: Run with Bash description: `"Regenerate Conforma resolution guide for active run"`:

   ```bash
   ~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/generate_resolution_guide.py
   ```

   This is the complete command — it takes no arguments. On failure (missing inputs, unreadable context.yaml), report the exact error and stop; do not fall back to manual guide composition.

2. **Present the complete TODO/DONE preview and deterministic submission question**: Run `present_conforma_report.py`. Copy the content between `BEGIN_VERBATIM_TODO_AND_DONE` and `END_VERBATIM_TODO_AND_DONE` verbatim into the response text, rendered as markdown (not in a code block), followed by the question and options between `BEGIN_SUBMISSION_QUESTION` and `END_SUBMISSION_QUESTION`. The agent MUST NOT paste the full guide, omit DONE sections, summarize, or add commentary. The complete report block must appear before the submission question, and the question MUST be asked in a subsequent turn (display-before-question rule).

3. **Offer re-submission** (requires user confirmation — separate turn after step 2): Use the deterministic question emitted by `present_conforma_report.py`. Do NOT auto-submit.

   The dry-run command remains available when the submission prompt must be regenerated or inspected independently:

   ```bash
   ~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/submit_resolution_guide.py --dry-run
   ```

   If the user declines, render the `skip_display` field verbatim. If the user confirms, run without `--dry-run`:

   ```bash
   ~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/submit_resolution_guide.py
   ```
