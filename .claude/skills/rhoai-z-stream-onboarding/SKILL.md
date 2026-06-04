---
name: rhoai-z-stream-onboarding
description: Master orchestrator for the full RHOAI Z-stream onboarding pipeline (RBC Release → RBC Main → Konflux → Apply Z-Stream Changes). Idempotent - run any number of times for the same release.
allowed-tools: Bash, AskUserQuestion
user-invocable: true
---

# RHOAI Z-Stream Onboarding

Orchestrates the complete RHOAI z-stream release onboarding pipeline with state tracking and idempotent re-run capability:

1. **RBC Release** — Update release branch on RHOAI-Build-Config for z-stream
2. **RBC Main** — Update main branch Tekton fragments for z-stream
3. **Konflux** — Update konflux-release-data for z-stream
4. **Apply Z-Stream Changes** — Trigger GitHub Actions workflow to apply z-stream changes in konflux-central

**Re-run model:** Invoke this skill any number of times for the same z-stream release. Each run checks which steps are complete and executes only the next unblocked steps.

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
/rhoai-z-stream-onboarding
/rhoai-z-stream-onboarding --resume
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 1: Check for resume mode

Check if there's an existing state file in the current directory that can be resumed:

```bash
STATE_FILES=(rhoai-zstream-rhoai-*-state.json)
if [[ -f "${STATE_FILES[0]}" && "${STATE_FILES[0]}" != "rhoai-zstream-rhoai-*-state.json" ]]; then
  EXISTING_STATE="${STATE_FILES[0]}"
  echo "Found existing state file: $EXISTING_STATE"
  
  # Ask user if they want to resume
  # Use AskUserQuestion to ask:
  # "Do you want to resume the existing pipeline or start a new one?"
  # Options: "Resume existing pipeline", "Start new pipeline"
  
  # If "Resume existing pipeline":
  #   Run: uv run --script "$COMMON_SCRIPTS_DIR/run_z_stream_pipeline.py" --resume "$EXISTING_STATE"
  #   Exit after completion
fi
```

## Step 2: Collect inputs for new pipeline

If not resuming, ask the user using AskUserQuestion:

**Question 1 - Previous version:**
> What is the previous RHOAI z-stream version?
> Examples: `rhoai-3.4.1`, `rhoai-3.4.0`, `3.4.1`, `3.4.0-ea.1`

→ Store in `PREVIOUS_VERSION` (normalize by stripping `rhoai-` prefix and adding `.0` if needed).

**Question 2 - New version:**
> What is the new RHOAI z-stream version?
> Examples: `rhoai-3.4.2`, `rhoai-3.4.1`, `3.4.2`, `3.4.1-ea.1`

→ Store in `NEW_VERSION` (normalize by stripping `rhoai-` prefix and adding `.0` if needed).

**Question 3 - Konflux clone directory (optional):**
> What directory should be used for konflux-release-data clone?
> Default: konflux-release-data

→ Store in `REPO_DIR`. Default: `konflux-release-data`.

**Question 4 - Jira tracking:**
> Do you want to create a Jira tracking issue or use an existing one?
> Options: 
>   - Create new Jira (Recommended)
>   - Use existing Jira URL
>   - Skip Jira creation

→ Store choice in `JIRA_CHOICE`.
→ If "Use existing Jira URL", ask for the URL and store in `JIRA_URL`.

**Question 5 - Dry-run mode (optional):**
> Should this run in dry-run mode?
> Note: Dry-run will preview all changes but not create PRs/MRs or Jira.
> Options: Yes, No (Recommended)

→ Store in `DRY_RUN`. Default: `no`.

## Step 3: Execute the pipeline

Normalize version strings and execute with real-time progress streaming:

```bash
# Strip 'rhoai-' prefix if present (case-insensitive)
PREV_NORMALIZED="${PREVIOUS_VERSION#rhoai-}"
PREV_NORMALIZED="${PREV_NORMALIZED#RHOAI-}"
NEW_NORMALIZED="${NEW_VERSION#rhoai-}"
NEW_NORMALIZED="${NEW_NORMALIZED#RHOAI-}"

# Add .0 patch if user provided x.y format (e.g., 3.4 -> 3.4.0)
# Z-stream requires patch versions (x.y.z)
if [[ "$PREV_NORMALIZED" =~ ^[0-9]+\.[0-9]+$ ]]; then
  PREV_NORMALIZED="${PREV_NORMALIZED}.0"
  echo "Note: Normalized previous version to patch format: $PREV_NORMALIZED"
fi

if [[ "$NEW_NORMALIZED" =~ ^[0-9]+\.[0-9]+$ ]]; then
  NEW_NORMALIZED="${NEW_NORMALIZED}.0"
  echo "Note: Normalized new version to patch format: $NEW_NORMALIZED"
fi

# Build command with normalized versions
CMD="uv run --script $COMMON_SCRIPTS_DIR/run_z_stream_pipeline.py $PREV_NORMALIZED $NEW_NORMALIZED"

# Add optional arguments
if [[ "$REPO_DIR" != "konflux-release-data" ]]; then
  CMD="$CMD --repo-dir $REPO_DIR"
fi

if [[ "$JIRA_CHOICE" == "Use existing Jira URL" && -n "$JIRA_URL" ]]; then
  CMD="$CMD --jira-url $JIRA_URL"
fi

if [[ "$DRY_RUN" == "yes" ]]; then
  CMD="$CMD --dry-run"
fi

# Execute with unbuffered output for real-time progress
# Use 'script -c' to force unbuffered output or direct execution
echo "Starting Z-stream onboarding pipeline..."
echo "Normalized versions: $PREV_NORMALIZED → $NEW_NORMALIZED"
echo "Command: $CMD"
echo ""

# Execute directly (Bash tool streams output in real-time)
eval "$CMD"
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  echo ""
  echo "✅ Pipeline completed successfully!"
else
  echo ""
  echo "❌ Pipeline failed with exit code $EXIT_CODE"
  exit $EXIT_CODE
fi
```

That's it! The Python script handles:
- Prerequisites checking
- Jira creation/retrieval
- State management
- Step execution with dependency tracking
- Jira status updates (In Progress → Resolved/Failed)
- Final summary and cleanup
- Automatic resume on re-run

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
