# RHOAI Release Jira

Creates or retrieves a Jira issue for RHOAI release onboarding with child tasks for tracking each pipeline step:
- Parent Issue: RHOAI Release Onboarding {previous} → {new}
- Child Task 1: RBC Release - Create release branch
- Child Task 2: RBC Main - Onboard to main branch
- Child Task 3: Konflux - Update konflux-release-data

Updates child tasks with PR/MR URLs and status as the pipeline progresses.

## Prerequisites

- Jira credentials must be configured
- Access to RHOAIENG project

## Usage

```
/rhoai-release-jira
/rhoai-release-jira --jira-url <existing-url>
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 0: Parse inputs

Ask the user using AskUserQuestion:

**Question 1 - Existing Jira:**
> Do you have an existing Jira issue for this release onboarding?
> Options: Yes (provide URL), No (create new)

→ If `Yes`: Store in `JIRA_URL` and skip to Step 2.
→ If `No`: Continue to Step 1.

**Question 2 - Previous version:**
> What is the previous RHOAI version?
> Examples: `rhoai-3.4`, `rhoai-3.5-ea.1`

→ Store in `PREVIOUS_VERSION`.

**Question 3 - New version:**
> What is the new RHOAI version?
> Examples: `rhoai-3.5`, `rhoai-3.5-ea.2`

→ Store in `NEW_VERSION`.

---

## Step 1: Create parent Jira issue

Create the parent issue using the Jira Python library:

```python
import os
from jira import JIRA

jira_url = os.getenv("JIRA_URL", "https://issues.redhat.com")
jira_token = os.getenv("JIRA_TOKEN")

jira = JIRA(server=jira_url, token_auth=jira_token)

parent_issue = jira.create_issue(
    project="RHOAIENG",
    summary=f"RHOAI Release Onboarding: {PREVIOUS_VERSION} → {NEW_VERSION}",
    description=f"""
RHOAI release onboarding automation tracking.

Previous Version: {PREVIOUS_VERSION}
New Version: {NEW_VERSION}

This issue tracks the 3-step onboarding pipeline:
1. RBC Release - Create release branch on RHOAI-Build-Config
2. RBC Main - Onboard catalog and Tekton to main branch
3. Konflux - Update konflux-release-data

Child tasks will be updated with PR/MR URLs as automation completes.
    """,
    issuetype={"name": "Task"},
)

parent_key = parent_issue.key
```

---

## Step 2: Create child tasks

Create 3 child tasks linked to the parent:

```python
child_tasks = []

# Task 1: RBC Release
task1 = jira.create_issue(
    project="RHOAIENG",
    summary=f"RBC Release: {PREVIOUS_VERSION} → {NEW_VERSION}",
    description=f"""
Create release branch on RHOAI-Build-Config.

- Rename Tekton pipeline files
- Update version references
- Update bundle-patch.yaml
- Create PR to release branch

Automation: /rhoai-rbc-release
    """,
    issuetype={"name": "Sub-task"},
    parent={"key": parent_key},
)
child_tasks.append(("rbc_release", task1.key))

# Task 2: RBC Main
task2 = jira.create_issue(
    project="RHOAIENG",
    summary=f"RBC Main: Onboard {NEW_VERSION} to main branch",
    description=f"""
Onboard new version to RHOAI-Build-Config main branch.

- Copy catalog directory
- Generate new Tekton pipeline files
- Create PR to main branch

Automation: /rhoai-rbc-main
    """,
    issuetype={"name": "Sub-task"},
    parent={"key": parent_key},
)
child_tasks.append(("rbc_main", task2.key))

# Task 3: Konflux
task3 = jira.create_issue(
    project="RHOAIENG",
    summary=f"Konflux: Onboard {NEW_VERSION} to konflux-release-data",
    description=f"""
Update konflux-release-data repository.

- Copy tenant directory
- Create RPA files
- Update kustomization
- Create GitLab MR

Automation: /rhoai-konflux-onboard
    """,
    issuetype={"name": "Sub-task"},
    parent={"key": parent_key},
)
child_tasks.append(("konflux", task3.key))
```

---

## Step 3: Output Jira information

Print the Jira URLs and save to a state file:

```python
import json

state = {
    "parent_issue": {
        "key": parent_key,
        "url": f"{jira_url}/browse/{parent_key}"
    },
    "child_tasks": {
        step: {
            "key": key,
            "url": f"{jira_url}/browse/{key}"
        }
        for step, key in child_tasks
    }
}

# Save to file
with open("rhoai-release-jira-state.json", "w") as f:
    json.dump(state, f, indent=2)

print(f"""
JIRA TRACKING CREATED

Parent Issue: {state['parent_issue']['url']}
  {parent_key}: RHOAI Release Onboarding: {PREVIOUS_VERSION} → {NEW_VERSION}

Child Tasks:
  1. {state['child_tasks']['rbc_release']['url']}
     RBC Release: {PREVIOUS_VERSION} → {NEW_VERSION}
     
  2. {state['child_tasks']['rbc_main']['url']}
     RBC Main: Onboard {NEW_VERSION} to main branch
     
  3. {state['child_tasks']['konflux']['url']}
     Konflux: Onboard {NEW_VERSION} to konflux-release-data

State saved to: rhoai-release-jira-state.json

Next: /rhoai-release-onboard (will auto-update Jira with PR/MR URLs)
""")
```

---

## Helper Function: Update Child Task

This will be called by the orchestrator:

```python
def update_child_task(jira, task_key, pr_url=None, status="In Progress"):
    """Update child task with PR/MR URL and status."""
    
    # Add comment with PR/MR URL
    if pr_url:
        jira.add_comment(
            task_key,
            f"Automation completed. PR/MR: {pr_url}"
        )
    
    # Update status
    transitions = jira.transitions(task_key)
    for transition in transitions:
        if status.lower() in transition['name'].lower():
            jira.transition_issue(task_key, transition['id'])
            break
```

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `JIRA_TOKEN` not set | Step 1 | `export JIRA_TOKEN=your-token` |
| Permission denied | Step 1 | Check access to RHOAIENG project |
| Cannot create sub-task | Step 2 | Verify issue type "Sub-task" exists |
| State file exists | Step 3 | Remove old state or use `--jira-url` |
