---
name: rhoai-release-onboard
description: Master orchestrator for the full RHOAI release onboarding pipeline (RBC Release → RBC Main → Konflux). Idempotent - run any number of times for the same release.
allowed-tools: Bash
user-invocable: true
---

# RHOAI Release Onboard

Orchestrates the complete RHOAI release onboarding pipeline with state tracking and idempotent re-run capability:

1. **RBC Release** (`rhoai-rbc-release`) — Create release branch on RHOAI-Build-Config
2. **RBC Main** (`rhoai-rbc-main`) — Onboard catalog + Tekton to main branch
3. **Konflux** (`rhoai-konflux-onboard`) — Update konflux-release-data

**Re-run model:** Invoke this skill any number of times for the same release. Each run checks which steps are complete and executes only the next unblocked steps.

## Prerequisites

- `uv` must be installed and in PATH
- `git` must be installed and in PATH
- `jq` must be installed and in PATH (for JSON state management)
- `GITHUB_TOKEN` — GitHub personal access token with repo scope
- `KONFLUX_REPO_TOKEN` — GitLab personal access token with API scope
- `JIRA_TOKEN` — Jira personal access token (for tracking)
- **VPN active** for Konflux step

## Usage

```
/rhoai-release-onboard
/rhoai-release-onboard --resume
/rhoai-release-onboard --dry-run
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 0: Parse inputs and check prerequisites

**If `--resume` flag provided:**
  Look for existing `pipeline_state.json` in current directory or ask user for path.
  Load state and skip to Step 3.

**Otherwise (new pipeline run):**

Ask the user using AskUserQuestion:

**Question 1 - Previous version:**
> What is the previous RHOAI version?
> Examples: `rhoai-3.4`, `rhoai-3.5-ea.1`

→ Store in `PREVIOUS_VERSION`.

**Question 2 - New version:**
> What is the new RHOAI version?
> Examples: `rhoai-3.5`, `rhoai-3.5-ea.2`

→ Store in `NEW_VERSION`.

**Question 3 - Konflux clone directory:**
> What directory should be used for konflux-release-data clone?
> Default: konflux-release-data

→ Store in `REPO_DIR`. Default: `konflux-release-data`.

**Question 4 - Dry-run mode:**
> Should this run in dry-run mode?
> Note: Dry-run will preview all changes but not create PRs/MRs.
> Options: Yes, No (Recommended for production releases)

→ Store in `DRY_RUN`. Default: `no`.

**Check prerequisites:**

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "GITHUB_TOKEN KONFLUX_REPO_TOKEN JIRA_TOKEN" \
  --tools "uv git jq"
```

On exit 1: display error and stop.

---

## Step 0.5: Create or retrieve Jira tracking issue

Ask the user using AskUserQuestion:

**Question - Existing Jira:**
> Do you have an existing Jira issue for this release?
> Options: Yes (provide URL), No (create new)

**If "Yes":**
- Ask for Jira URL
- Extract parent key from URL
- Retrieve child tasks using the Jira script:

```bash
PARENT_KEY="<extracted-from-url>"  # e.g., RHOAIENG-12345
JIRA_STATE=$(uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" get "$PARENT_KEY" 2>&1)

# Extract child task keys from output
# Store in variables: RBC_RELEASE_TASK, RBC_MAIN_TASK, KONFLUX_TASK
```

**If "No":**
- Create new Jira parent and child tasks:

```bash
JIRA_OUTPUT=$(uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" \
  create "$PREVIOUS_VERSION" "$NEW_VERSION" 2>&1)
JIRA_EXIT=$?

if [[ $JIRA_EXIT -ne 0 ]]; then
  echo "ERROR: Failed to create Jira tracking issue"
  echo "$JIRA_OUTPUT"
  exit 1
fi

echo "$JIRA_OUTPUT"

# Extract Jira keys from state file
JIRA_STATE_FILE="rhoai-release-${NEW_VERSION}-jira.json"
PARENT_KEY=$(jq -r '.parent_issue.key' "$JIRA_STATE_FILE")
RBC_RELEASE_TASK=$(jq -r '.child_tasks.rbc_release.key' "$JIRA_STATE_FILE")
RBC_MAIN_TASK=$(jq -r '.child_tasks.rbc_main.key' "$JIRA_STATE_FILE")
KONFLUX_TASK=$(jq -r '.child_tasks.konflux.key' "$JIRA_STATE_FILE")
PARENT_URL=$(jq -r '.parent_issue.url' "$JIRA_STATE_FILE")

echo ""
echo "✓ Jira tracking created: $PARENT_URL"
echo ""
```

---

## Step 1: Initialize pipeline state

Create `pipeline_state.json` in current directory:

```bash
STATE_FILE="$(pwd)/rhoai-release-${NEW_VERSION}-state.json"

cat > "$STATE_FILE" <<EOF
{
  "release_info": {
    "previous_version": "$PREVIOUS_VERSION",
    "new_version": "$NEW_VERSION",
    "konflux_repo_dir": "$REPO_DIR",
    "dry_run": $([ "$DRY_RUN" == "yes" ] && echo "true" || echo "false"),
    "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  },
  "jira": {
    "parent_key": "$PARENT_KEY",
    "parent_url": "$PARENT_URL",
    "child_tasks": {
      "rbc_release": "$RBC_RELEASE_TASK",
      "rbc_main": "$RBC_MAIN_TASK",
      "konflux": "$KONFLUX_TASK"
    }
  },
  "steps": {
    "rbc_release": {
      "status": "pending",
      "pr_url": null,
      "completed_at": null,
      "depends_on": []
    },
    "rbc_main": {
      "status": "pending",
      "pr_url": null,
      "completed_at": null,
      "depends_on": ["rbc_release"]
    },
    "konflux": {
      "status": "pending",
      "mr_url": null,
      "completed_at": null,
      "depends_on": ["rbc_main"]
    }
  }
}
EOF

echo "Pipeline state initialized: $STATE_FILE"
echo "Jira parent: $PARENT_URL"
```

---

## Step 2: Display pipeline summary

Print:
```
╔══════════════════════════════════════════════════════════════╗
║          RHOAI RELEASE ONBOARDING PIPELINE                   ║
╚══════════════════════════════════════════════════════════════╝

Previous version: <PREVIOUS_VERSION>
New version:      <NEW_VERSION>
Dry-run mode:     <DRY_RUN>

Pipeline Steps:
  1. RBC Release      → Create release branch (RHOAI-Build-Config)
  2. RBC Main         → Onboard to main branch (RHOAI-Build-Config)
  3. Konflux Onboard  → Update konflux-release-data

State file: <STATE_FILE>

═══════════════════════════════════════════════════════════════
```

---

## Step 3: Execute pipeline steps

For each step in order (`rbc_release`, `rbc_main`, `konflux`):

### 3a. Check step status

```bash
STEP_NAME="<step>"  # rbc_release, rbc_main, or konflux
STEP_STATUS=$(jq -r ".steps.$STEP_NAME.status" "$STATE_FILE")

if [[ "$STEP_STATUS" == "done" ]]; then
  PR_URL=$(jq -r ".steps.$STEP_NAME.pr_url // .steps.$STEP_NAME.mr_url" "$STATE_FILE")
  echo "✓ Step $STEP_NAME already completed: $PR_URL"
  continue  # Skip to next step
fi
```

### 3b. Check dependencies

```bash
DEPS=$(jq -r ".steps.$STEP_NAME.depends_on[]?" "$STATE_FILE")
for DEP in $DEPS; do
  DEP_STATUS=$(jq -r ".steps.$DEP.status" "$STATE_FILE")
  if [[ "$DEP_STATUS" != "done" ]]; then
    echo "⏸  Step $STEP_NAME blocked: waiting for $DEP to complete"
    exit 0  # Stop here, resume later
  fi
done
```

### 3c. Execute step

Update state to mark step as in progress:

```bash
jq ".steps.$STEP_NAME.status = \"in_progress\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
```

**For `rbc_release` step:**

```bash
echo "═══════════════════════════════════════════════════════════════"
echo "STEP 1/3: RBC Release"
echo "═══════════════════════════════════════════════════════════════"

if [[ "$DRY_RUN" == "yes" ]]; then
  OUTPUT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_release.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" --dry-run 2>&1)
  STEP_EXIT=$?
else
  OUTPUT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_release.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" 2>&1)
  STEP_EXIT=$?
fi

echo "$OUTPUT"

if [[ $STEP_EXIT -eq 0 ]]; then
  PR_URL=$(echo "$OUTPUT" | grep -oP 'https://github\.com/[^/]+/[^/]+/pull/\d+' | head -1)
  jq ".steps.rbc_release.status = \"done\" | \
      .steps.rbc_release.pr_url = \"${PR_URL:-N/A}\" | \
      .steps.rbc_release.completed_at = \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" \
    "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  echo "✓ RBC Release completed"
  
  # Update Jira child task
  JIRA_TASK=$(jq -r '.jira.child_tasks.rbc_release' "$STATE_FILE")
  if [[ "$JIRA_TASK" != "null" && -n "$PR_URL" ]]; then
    echo "Updating Jira task $JIRA_TASK..."
    uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$JIRA_TASK" \
      --pr-url "$PR_URL" --status "Resolved" 2>&1 | grep -E "^(✓|⚠|ERROR)" || true
  fi
else
  jq ".steps.rbc_release.status = \"failed\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  echo "✗ RBC Release failed (exit $STEP_EXIT)"
  
  # Update Jira child task to failed
  JIRA_TASK=$(jq -r '.jira.child_tasks.rbc_release' "$STATE_FILE")
  if [[ "$JIRA_TASK" != "null" ]]; then
    uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$JIRA_TASK" \
      --status "Failed" 2>&1 | grep -E "^(✓|⚠|ERROR)" || true
  fi
  exit 1
fi
```

**For `rbc_main` step:**

```bash
echo "═══════════════════════════════════════════════════════════════"
echo "STEP 2/3: RBC Main Onboard"
echo "═══════════════════════════════════════════════════════════════"

if [[ "$DRY_RUN" == "yes" ]]; then
  OUTPUT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_main.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" --dry-run 2>&1)
  STEP_EXIT=$?
else
  OUTPUT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_main.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" 2>&1)
  STEP_EXIT=$?
fi

echo "$OUTPUT"

if [[ $STEP_EXIT -eq 0 ]]; then
  PR_URL=$(echo "$OUTPUT" | grep -oP 'https://github\.com/[^/]+/[^/]+/pull/\d+' | head -1)
  jq ".steps.rbc_main.status = \"done\" | \
      .steps.rbc_main.pr_url = \"${PR_URL:-N/A}\" | \
      .steps.rbc_main.completed_at = \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" \
    "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  echo "✓ RBC Main completed"
  
  # Update Jira child task
  JIRA_TASK=$(jq -r '.jira.child_tasks.rbc_main' "$STATE_FILE")
  if [[ "$JIRA_TASK" != "null" && -n "$PR_URL" ]]; then
    echo "Updating Jira task $JIRA_TASK..."
    uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$JIRA_TASK" \
      --pr-url "$PR_URL" --status "Resolved" 2>&1 | grep -E "^(✓|⚠|ERROR)" || true
  fi
else
  jq ".steps.rbc_main.status = \"failed\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  echo "✗ RBC Main failed (exit $STEP_EXIT)"
  
  # Update Jira child task to failed
  JIRA_TASK=$(jq -r '.jira.child_tasks.rbc_main' "$STATE_FILE")
  if [[ "$JIRA_TASK" != "null" ]]; then
    uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$JIRA_TASK" \
      --status "Failed" 2>&1 | grep -E "^(✓|⚠|ERROR)" || true
  fi
  exit 1
fi
```

**For `konflux` step:**

```bash
echo "═══════════════════════════════════════════════════════════════"
echo "STEP 3/3: Konflux Onboard"
echo "═══════════════════════════════════════════════════════════════"

if [[ "$DRY_RUN" == "yes" ]]; then
  OUTPUT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_konflux_onboard.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" --repo-dir "$REPO_DIR" --dry-run 2>&1)
  STEP_EXIT=$?
else
  OUTPUT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_konflux_onboard.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" --repo-dir "$REPO_DIR" 2>&1)
  STEP_EXIT=$?
fi

echo "$OUTPUT"

if [[ $STEP_EXIT -eq 0 ]]; then
  MR_URL=$(echo "$OUTPUT" | grep -oP 'https://gitlab\.[^/]+/[^/]+/[^/]+/-/merge_requests/\d+' | head -1)
  jq ".steps.konflux.status = \"done\" | \
      .steps.konflux.mr_url = \"${MR_URL:-N/A}\" | \
      .steps.konflux.completed_at = \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" \
    "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  echo "✓ Konflux Onboard completed"
  
  # Update Jira child task
  JIRA_TASK=$(jq -r '.jira.child_tasks.konflux' "$STATE_FILE")
  if [[ "$JIRA_TASK" != "null" && -n "$MR_URL" ]]; then
    echo "Updating Jira task $JIRA_TASK..."
    uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$JIRA_TASK" \
      --pr-url "$MR_URL" --status "Resolved" 2>&1 | grep -E "^(✓|⚠|ERROR)" || true
  fi
else
  jq ".steps.konflux.status = \"failed\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  echo "✗ Konflux Onboard failed (exit $STEP_EXIT)"
  
  # Update Jira child task to failed
  JIRA_TASK=$(jq -r '.jira.child_tasks.konflux' "$STATE_FILE")
  if [[ "$JIRA_TASK" != "null" ]]; then
    uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$JIRA_TASK" \
      --status "Failed" 2>&1 | grep -E "^(✓|⚠|ERROR)" || true
  fi
  exit 1
fi
```

---

## Step 4: Final summary

Check if all steps are done:

```bash
ALL_DONE=$(jq -r '[.steps[].status] | all(. == "done")' "$STATE_FILE")

if [[ "$ALL_DONE" == "true" ]]; then
  RBC_RELEASE_PR=$(jq -r '.steps.rbc_release.pr_url' "$STATE_FILE")
  RBC_MAIN_PR=$(jq -r '.steps.rbc_main.pr_url' "$STATE_FILE")
  KONFLUX_MR=$(jq -r '.steps.konflux.mr_url' "$STATE_FILE")
  PARENT_KEY=$(jq -r '.jira.parent_key' "$STATE_FILE")
  PARENT_URL=$(jq -r '.jira.parent_url' "$STATE_FILE")

  # Update parent Jira with final summary
  if [[ "$PARENT_KEY" != "null" ]]; then
    echo "Updating parent Jira issue with final summary..."
    JIRA_COMMENT="Release Onboarding Complete

All automation steps finished successfully.

Previous Version: $PREVIOUS_VERSION
New Version: $NEW_VERSION

Pull Requests / Merge Requests:
- RBC Release: $RBC_RELEASE_PR
- RBC Main: $RBC_MAIN_PR
- Konflux: $KONFLUX_MR

Next: Review and merge the PRs/MRs, monitor CI/CD pipelines, test builds."

    # Add comment with all PR/MR URLs and update status
    uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$PARENT_KEY" \
      --pr-url "$JIRA_COMMENT" --status "Resolved" 2>&1 | grep -E "^(✓|⚠|ERROR)" || true
    
    echo "✓ Jira updated: $PARENT_URL"
    echo ""
  fi

  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║      🎉 RHOAI RELEASE ONBOARDING COMPLETE! 🎉               ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  echo "Release: $PREVIOUS_VERSION → $NEW_VERSION"
  echo ""
  echo "Jira: $PARENT_URL"
  echo ""
  echo "Pull Requests / Merge Requests:"
  echo "  1. RBC Release:  $RBC_RELEASE_PR"
  echo "  2. RBC Main:     $RBC_MAIN_PR"
  echo "  3. Konflux MR:   $KONFLUX_MR"
  echo ""
  echo "Next steps:"
  echo "  • Review and merge the PRs/MRs"
  echo "  • Monitor CI/CD pipelines"
  echo "  • Test the new release builds"
  echo ""
  echo "State file: $STATE_FILE"
  echo "═══════════════════════════════════════════════════════════════"
else
  echo ""
  echo "Pipeline paused. Some steps remain:"
  jq -r '.steps | to_entries[] | select(.value.status != "done") | "  • \(.key): \(.value.status)"' "$STATE_FILE"
  echo ""
  echo "To resume: /rhoai-release-onboard --resume"
  echo "State file: $STATE_FILE"
fi
```

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITHUB_TOKEN` not set | Step 0 | `export GITHUB_TOKEN=your-token` |
| `KONFLUX_REPO_TOKEN` not set | Step 0 | `export KONFLUX_REPO_TOKEN=your-token` |
| `JIRA_TOKEN` not set | Step 0.5 | `export JIRA_TOKEN=your-jira-token` |
| `jq` not installed | Step 0 | `brew install jq` or `dnf install jq` |
| Jira creation fails | Step 0.5 | Check JIRA_TOKEN permissions on RHOAIENG project |
| Step failed | Step 3 | Check step output, fix issue, re-run with `--resume` |
| Dependencies not met | Step 3b | Wait for dependent step to complete, then re-run |
| State file not found | Step 0 | Provide path to existing state or start new pipeline |
