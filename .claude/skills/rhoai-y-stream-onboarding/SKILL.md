---
name: rhoai-y-stream-onboarding
description: Master orchestrator for the full RHOAI Y-stream onboarding pipeline (RBC Release → RBC Main → Konflux → PipelineRun Replicator). Idempotent - run any number of times for the same release.
allowed-tools: Bash, AskUserQuestion
user-invocable: true
---

# RHOAI Y-Stream Onboarding

Orchestrates the complete RHOAI release onboarding pipeline with state tracking and idempotent re-run capability:

1. **RBC Release** — Create release branch on RHOAI-Build-Config
2. **RBC Main** — Onboard catalog + Tekton to main branch
3. **Konflux** — Update konflux-release-data
4. **PipelineRun Replicator** — Replicate PipelineRuns in konflux-central

**Re-run model:** Invoke this skill any number of times for the same release. Each run checks which steps are complete and executes only the next unblocked steps.

## Prerequisites

- `uv` must be installed and in PATH
- `git` must be installed and in PATH
- `jq` must be installed and in PATH
- `GITHUB_TOKEN` — GitHub personal access token with repo scope
- `KONFLUX_REPO_TOKEN` — GitLab personal access token with API scope
- `JIRA_API_TOKEN` — Jira personal access token (for tracking)
- **VPN active** for Konflux step

## Usage

```
/rhoai-y-stream-onboarding
/rhoai-y-stream-onboarding --resume
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 1: Check for resume mode

Check if there's an existing state file in the current directory that can be resumed:

```bash
STATE_FILES=(rhoai-release-rhoai-*-state.json)
if [[ -f "${STATE_FILES[0]}" && "${STATE_FILES[0]}" != "rhoai-release-rhoai-*-state.json" ]]; then
  EXISTING_STATE="${STATE_FILES[0]}"
  echo "Found existing state file: $EXISTING_STATE"
  
  # Ask user if they want to resume
  # Use AskUserQuestion to ask:
  # "Do you want to resume the existing pipeline or start a new one?"
  # Options: "Resume existing pipeline", "Start new pipeline"
  
  # If "Resume existing pipeline":
  #   Run: uv run --script "$COMMON_SCRIPTS_DIR/run_y_stream_pipeline.py" --resume "$EXISTING_STATE"
  #   Exit after completion
fi
```

## Step 2: Collect inputs for new pipeline

If not resuming, collect ALL of the following inputs from the user.
You MUST ask ALL questions below before executing the pipeline.
Use the AskQuestion tool TWICE — once for versions, once for options.

### Round 1 — Version inputs (free-text)

Ask the user for both versions in a single message. Do NOT proceed until both are provided.

**Question 1 - Previous version:**
> What is the previous RHOAI version?
> Examples: `rhoai-3.4`, `rhoai-3.5-ea.1`

→ Store in `PREVIOUS_VERSION`.

**Question 2 - New version:**
> What is the new RHOAI version?
> Examples: `rhoai-3.5`, `rhoai-3.5-ea.2`

→ Store in `NEW_VERSION`.

### Round 2 — Pipeline options (structured choices)

After receiving the versions, you MUST present a SECOND AskQuestion form with these structured choices. Do NOT skip this step or use defaults silently.

**Question 3 - Jira tracking:**
Use AskQuestion with these options:
- id: `jira_choice`
- prompt: "How should Jira tracking be handled?"
- options:
  - `create_new` → "Create new Jira (Recommended)"
  - `use_existing` → "Use existing Jira URL"
  - `skip` → "Skip Jira creation"

→ Store choice in `JIRA_CHOICE`.
→ If "use_existing" is selected, ask the user for the Jira URL in a follow-up message and store in `JIRA_URL`.

**Question 4 - Dry-run mode:**
Use AskQuestion with these options (can be in the same AskQuestion call as Q3):
- id: `dry_run`
- prompt: "Should this run in dry-run mode? (Dry-run previews changes without creating PRs/MRs or Jira)"
- options:
  - `no` → "No — execute for real (Recommended)"
  - `yes` → "Yes — dry-run only"

→ Store in `DRY_RUN`. Default: `no`.

### Defaults

- `REPO_DIR` = `konflux-release-data` (always use default, do not ask)
- `JIRA_CHOICE` = `create_new` if user does not answer
- `DRY_RUN` = `no` if user does not answer

## CRITICAL EXECUTION RULES

**You MUST execute this pipeline as exactly 5 SEPARATE Bash calls (Steps 3–7).**
**NEVER combine multiple steps into a single Bash call.**
**After EACH Bash call, you MUST read the state file and display a progress summary as a regular text message.**

Bash output gets collapsed and the user cannot see it. The only way the user sees progress is through your text messages between Bash calls. If you skip the text messages, the user sees nothing.

STATE_FILE is `rhoai-release-${NEW_VERSION}-state.json`.

### How to display progress (do this after EVERY Bash call)

1. Read the STATE_FILE (use Bash: `cat "$STATE_FILE"`)
2. Parse the JSON
3. Display this as a **regular text message** (NOT inside Bash):

First time only — Jira info:
> 📋 **Jira Tracking**
> - Parent: RHOAIENG-XXXXX — <parent_url>
> - Subtask 1: RHOAIENG-XXXXX — RBC Release
> - Subtask 2: RHOAIENG-XXXXX — RBC Main
> - Subtask 3: RHOAIENG-XXXXX — Konflux
> - Subtask 4: RHOAIENG-XXXXX — PipelineRun Replicator

Every time — Progress:
> **Pipeline Progress [N/4]**
> ✅ Step 1 — RBC Release — <pr_url>
> ⏳ Step 2 — RBC Main — Pending
> ⏳ Step 3 — Konflux — Pending
> ⏳ Step 4 — PipelineRun Replicator — Pending

Use ✅ for `done` (include URL), ❌ for `failed`, ⏳ for `pending`.

---

## Step 3: Bash call 1 — Initialize + Execute Step 1 (RBC Release)

This is the FIRST Bash call. It creates Jira, initializes state, and runs Step 1.

```bash
SKILL_DIR="<absolute path to this SKILL.md's directory>"
COMMON_SCRIPTS_DIR="$SKILL_DIR/../common/scripts"
CMD="uv run --script $COMMON_SCRIPTS_DIR/run_y_stream_pipeline.py $PREVIOUS_VERSION $NEW_VERSION --single-step"
if [[ "$JIRA_CHOICE" == "use_existing" && -n "$JIRA_URL" ]]; then CMD="$CMD --jira-url $JIRA_URL"; fi
if [[ "$DRY_RUN" == "yes" ]]; then CMD="$CMD --dry-run"; fi
eval "$CMD"
```

**After this Bash call completes:** Read STATE_FILE. Display Jira info + progress as text. Then proceed to Step 4.

## Step 4: Bash call 2 — Execute Step 2 (RBC Main)

This is the SECOND Bash call. It resumes and runs the next pending step.

```bash
STATE_FILE="rhoai-release-${NEW_VERSION}-state.json"
uv run --script "$COMMON_SCRIPTS_DIR/run_y_stream_pipeline.py" --resume "$STATE_FILE" --single-step
```

**After this Bash call completes:** Read STATE_FILE. Display progress as text. Then proceed to Step 5.

## Step 5: Bash call 3 — Execute Step 3 (Konflux)

This is the THIRD Bash call.

```bash
STATE_FILE="rhoai-release-${NEW_VERSION}-state.json"
uv run --script "$COMMON_SCRIPTS_DIR/run_y_stream_pipeline.py" --resume "$STATE_FILE" --single-step
```

**After this Bash call completes:** Read STATE_FILE. Display progress as text. Then proceed to Step 6.

## Step 6: Bash call 4 — Execute Step 4 (PipelineRun Replicator)

This is the FOURTH Bash call.

```bash
STATE_FILE="rhoai-release-${NEW_VERSION}-state.json"
uv run --script "$COMMON_SCRIPTS_DIR/run_y_stream_pipeline.py" --resume "$STATE_FILE" --single-step
```

**After this Bash call completes:** Read STATE_FILE. Display progress as text. Then proceed to Step 7.

## Step 7: Final summary

Read the STATE_FILE one last time and display this as a regular text message:

> 🎉 **RHOAI Release Onboarding Complete!**
>
> **Release:** `<previous_version>` → `<new_version>`
>
> 📋 **Jira:** `<parent_url>`
>
> **Pull Requests / Merge Requests:**
> 1. RBC Release — `<pr_url>`
> 2. RBC Main — `<pr_url>`
> 3. Konflux — `<mr_url>`
> 4. PipelineRun Replicator — `<run_url>`
>
> ✅ A summary comment with all PR/MR links has been posted to the parent Jira.
>
> **Next Steps:**
> 1. Review and merge all PRs/MRs
> 2. Monitor CI/CD pipeline execution
> 3. Verify builds are successful
> 4. Manually close the Jira when verified

**Error handling:** If any step fails (exit code != 0), stop immediately. Display the progress showing which step failed (❌) and tell the user to fix the issue and re-run.

---

## Error Reference

| Error | Action |
|-------|--------|
| `GITHUB_TOKEN` not set | `export GITHUB_TOKEN=your-token` |
| `KONFLUX_REPO_TOKEN` not set | `export KONFLUX_REPO_TOKEN=your-token` |
| `JIRA_API_TOKEN` not set | `export JIRA_API_TOKEN=your-jira-token` |
| `uv`/`git`/`jq` not installed | Install the missing tool |
| Step failed | Check output, fix issue, re-run skill to resume |
| VPN not active | Connect to VPN before Konflux step |
