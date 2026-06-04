---
name: rhoai-zstream-jira
description: Creates or retrieves a Jira issue for RHOAI z-stream release onboarding with child tasks for tracking each pipeline step
allowed-tools: Bash, AskUserQuestion
user-invocable: true
---

# RHOAI Z-Stream Release Jira

Creates or retrieves a Jira issue for RHOAI z-stream release onboarding with child tasks for tracking each pipeline step:
- Parent Issue: RHOAI Z-Stream Release {previous} → {new}
- Child Task 1: RBC Z-Stream Release - Update release branch
- Child Task 2: RBC Z-Stream Main - Update main branch Tekton fragments
- Child Task 3: Konflux Z-Stream - Update konflux-release-data

Updates child tasks with PR/MR URLs and status as the pipeline progresses.

## Prerequisites

- Jira credentials must be configured
- Access to RHOAIENG project

## Usage

```
/rhoai-zstream-jira
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 1: Parse inputs

Ask the user using AskUserQuestion:

**Question 1 - Existing Jira:**
> Do you have an existing Jira issue for this z-stream release onboarding?
> Options: Yes (provide URL), No (create new)

→ If `Yes`: Ask for the Jira URL using "Other" option, store in `JIRA_URL` and skip to Step 3.
→ If `No`: Continue to Step 2.

**Question 2 - Previous version:**
> What is the previous RHOAI z-stream version?
> Examples: `3.4.1`, `3.4.0-ea.1`, `rhoai-3.4.1`

→ Store in `PREVIOUS_VERSION`.

**Question 3 - New version:**
> What is the new RHOAI z-stream version?
> Examples: `3.4.2`, `3.4.1-ea.1`, `rhoai-3.4.2`

→ Store in `NEW_VERSION`.

---

## Step 2: Create new Jira

Only execute this step if user selected "No (create new)" in Question 1.

```bash
uv run --script "$COMMON_SCRIPTS_DIR/rhoai_zstream_jira.py" create "$PREVIOUS_VERSION" "$NEW_VERSION"
```

This will:
- Create parent issue in RHOAIENG project
- Create 3 child sub-tasks (RBC Release, RBC Main, Konflux)
- Save state to `rhoai-zstream-{NEW_VERSION}-jira.json`
- Print Jira URLs

Exit after completion.

---

## Step 3: Retrieve existing Jira

Only execute this step if user selected "Yes (provide URL)" in Question 1.

Extract the Jira key from the URL:

```bash
JIRA_KEY="${JIRA_URL##*/}"
```

Get the Jira details:

```bash
uv run --script "$COMMON_SCRIPTS_DIR/rhoai_zstream_jira.py" get "$JIRA_KEY"
```

This will:
- Display parent issue summary and status
- Display child tasks with their status
- Print all Jira URLs

---

## Output

The skill outputs:
- Parent Jira issue URL
- 3 child sub-task URLs
- State file location (for new Jira creation)

Next step: Run `/rhoai-z-stream-onboarding` which will automatically use this Jira for tracking.

---

## Error Reference

| Error | Action |
|-------|--------|
| `JIRA_TOKEN` not set | `export JIRA_TOKEN=your-token` or `export JIRA_API_TOKEN=your-token` |
| `JIRA_EMAIL` not set | `export JIRA_EMAIL=your-email@redhat.com` (for Atlassian Cloud) |
| Permission denied | Check access to RHOAIENG project |
| Cannot create sub-task | Verify issue type "Sub-task" exists in project |
| Jira not found | Verify the Jira URL is correct |
