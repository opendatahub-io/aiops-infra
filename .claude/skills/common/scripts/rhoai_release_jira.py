#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "jira>=3.5.0",
#     "python-dotenv>=1.0.0",
# ]
# ///
"""
RHOAI Release Jira Management

Creates parent issue and child tasks for RHOAI release onboarding.
Updates child tasks with PR/MR URLs and status.

Usage:
  rhoai_release_jira.py create <prev_version> <new_version>
  rhoai_release_jira.py update <task_key> --pr-url <url> --status <status>
  rhoai_release_jira.py comment <issue_key> <comment_text>
  rhoai_release_jira.py get <parent_key>

Environment:
  JIRA_URL - Jira server URL (default: https://issues.redhat.com)
  JIRA_TOKEN - Jira personal access token
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from jira import JIRA

# Load environment
load_dotenv()

JIRA_URL = os.getenv("JIRA_URL", "https://redhat.atlassian.net")
JIRA_TOKEN = os.getenv("JIRA_TOKEN") or os.getenv("JIRA_API_TOKEN")
JIRA_EMAIL = os.getenv("JIRA_EMAIL") or os.getenv("JIRA_USER_EMAIL") or os.getenv("JIRA_USERNAME")
JIRA_PROJECT = os.getenv("JIRA_PROJECT", "RHOAIENG")


def create_jira_client():
    """Create authenticated Jira client."""
    if not JIRA_TOKEN:
        raise ValueError("JIRA_TOKEN/JIRA_API_TOKEN environment variable not set")

    # For Atlassian Cloud, use basic auth with email + API token
    if JIRA_EMAIL:
        return JIRA(server=JIRA_URL, basic_auth=(JIRA_EMAIL, JIRA_TOKEN))
    else:
        # Fallback to token auth
        return JIRA(server=JIRA_URL, token_auth=JIRA_TOKEN)


def create_parent_and_children(prev_version: str, new_version: str):
    """Create parent issue and 3 child tasks."""
    jira = create_jira_client()

    # Create parent issue
    print(f"Creating parent issue in {JIRA_PROJECT}...")
    parent_issue = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"RHOAI Release Onboarding: {prev_version} → {new_version}",
        description=f"""RHOAI release onboarding automation tracking.

Previous Version: {prev_version}
New Version: {new_version}

This issue tracks the 4-step onboarding pipeline:
1. RBC Release - Create release branch on RHOAI-Build-Config
2. RBC Main - Onboard catalog and Tekton to main branch
3. Konflux - Update konflux-release-data
4. PipelineRun Replicator - Replicate PipelineRuns in konflux-central

Child tasks will be updated with PR/MR URLs as automation completes.
""",
        issuetype={"name": "Task"},
    )

    parent_key = parent_issue.key
    print(f"✓ Created parent: {parent_key}")

    # Create child tasks
    child_tasks = {}

    # Task 1: RBC Release
    print("Creating child task 1: RBC Release...")
    task1 = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"RBC Release: {prev_version} → {new_version}",
        description=f"""Create release branch on RHOAI-Build-Config.

- Rename Tekton pipeline files
- Update version references
- Update bundle-patch.yaml
- Create PR to release branch

Automation: /rhoai-rbc-release
""",
        issuetype={"name": "Sub-task"},
        parent={"key": parent_key},
    )
    child_tasks["rbc_release"] = task1.key
    print(f"✓ Created: {task1.key}")

    # Task 2: RBC Main
    print("Creating child task 2: RBC Main...")
    task2 = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"RBC Main: Onboard {new_version} to main branch",
        description=f"""Onboard new version to RHOAI-Build-Config main branch.

- Copy catalog directory
- Generate new Tekton pipeline files
- Create PR to main branch

Automation: /rhoai-rbc-main
""",
        issuetype={"name": "Sub-task"},
        parent={"key": parent_key},
    )
    child_tasks["rbc_main"] = task2.key
    print(f"✓ Created: {task2.key}")

    # Task 3: Konflux
    print("Creating child task 3: Konflux...")
    task3 = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"Konflux: Onboard {new_version} to konflux-release-data",
        description=f"""Update konflux-release-data repository.

- Copy tenant directory
- Create RPA files
- Update kustomization
- Create GitLab MR

Automation: /rhoai-konflux-onboard
""",
        issuetype={"name": "Sub-task"},
        parent={"key": parent_key},
    )
    child_tasks["konflux"] = task3.key
    print(f"✓ Created: {task3.key}")

    # Task 4: PipelineRun Replicator
    print("Creating child task 4: PipelineRun Replicator...")
    task4 = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"PipelineRun Replicator: {prev_version} → {new_version}",
        description=f"""Replicate PipelineRuns in konflux-central from previous to new version.

- Trigger GitHub Actions workflow
- Replicate pull-request PipelineRuns
- Replicate push PipelineRuns
- Monitor workflow completion

Automation: /trigger-pipelinerun-replicator
""",
        issuetype={"name": "Sub-task"},
        parent={"key": parent_key},
    )
    child_tasks["pipelinerun_replicator"] = task4.key
    print(f"✓ Created: {task4.key}")

    # Build state
    state = {
        "release_info": {
            "previous_version": prev_version,
            "new_version": new_version,
        },
        "parent_issue": {
            "key": parent_key,
            "url": f"{JIRA_URL}/browse/{parent_key}"
        },
        "child_tasks": {
            step: {
                "key": key,
                "url": f"{JIRA_URL}/browse/{key}"
            }
            for step, key in child_tasks.items()
        }
    }

    # Save state
    state_file = f"rhoai-release-{new_version}-jira.json"
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)

    # Print summary
    print("\n" + "="*60)
    print("JIRA TRACKING CREATED")
    print("="*60)
    print(f"\nParent Issue: {state['parent_issue']['url']}")
    print(f"  {parent_key}: RHOAI Release Onboarding: {prev_version} → {new_version}")
    print("\nChild Tasks:")
    print(f"  1. {state['child_tasks']['rbc_release']['url']}")
    print(f"     {child_tasks['rbc_release']}: RBC Release")
    print(f"\n  2. {state['child_tasks']['rbc_main']['url']}")
    print(f"     {child_tasks['rbc_main']}: RBC Main")
    print(f"\n  3. {state['child_tasks']['konflux']['url']}")
    print(f"     {child_tasks['konflux']}: Konflux")
    print(f"\n  4. {state['child_tasks']['pipelinerun_replicator']['url']}")
    print(f"     {child_tasks['pipelinerun_replicator']}: PipelineRun Replicator")
    print(f"\nState saved to: {state_file}")
    print("\nNext: /rhoai-y-stream-onboarding (will auto-update Jira with PR/MR URLs)")
    print("="*60)

    return state


def update_child_task(task_key: str, pr_url: str = None, status: str = None):
    """Update child task with PR/MR URL and/or status."""
    jira = create_jira_client()

    # Add comment with PR/MR URL
    if pr_url:
        print(f"Adding PR/MR URL to {task_key}...")
        jira.add_comment(
            task_key,
            f"Automation completed.\n\nPR/MR: {pr_url}"
        )
        print(f"✓ Added comment")

    # Update status
    if status:
        print(f"Updating {task_key} status to '{status}'...")
        transitions = jira.transitions(task_key)

        # Find matching transition
        transition_id = None
        for transition in transitions:
            if status.lower() in transition['name'].lower():
                transition_id = transition['id']
                break

        if transition_id:
            jira.transition_issue(task_key, transition_id)
            print(f"✓ Status updated to '{status}'")
        else:
            available = [t['name'] for t in transitions]
            print(f"⚠ Could not find transition matching '{status}'")
            print(f"  Available transitions: {', '.join(available)}")

    print(f"\n{JIRA_URL}/browse/{task_key}")


def add_comment_to_issue(issue_key: str, comment_text: str):
    """Add a comment to a Jira issue."""
    jira = create_jira_client()

    print(f"Adding comment to {issue_key}...")
    jira.add_comment(issue_key, comment_text)
    print(f"✓ Comment added to {JIRA_URL}/browse/{issue_key}")


def get_parent_info(parent_key: str):
    """Get parent issue and child tasks information."""
    jira = create_jira_client()

    parent = jira.issue(parent_key)

    print(f"\nParent: {JIRA_URL}/browse/{parent_key}")
    print(f"  Summary: {parent.fields.summary}")
    print(f"  Status: {parent.fields.status}")

    # Get child tasks
    print("\nChild Tasks:")
    for link in parent.fields.subtasks:
        child = jira.issue(link.key)
        print(f"  {link.key}: {child.fields.summary}")
        print(f"    Status: {child.fields.status}")
        print(f"    URL: {JIRA_URL}/browse/{link.key}")


def main():
    parser = argparse.ArgumentParser(description="RHOAI Release Jira Management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Create command
    create_parser = subparsers.add_parser("create", help="Create parent and child issues")
    create_parser.add_argument("prev_version", help="Previous version (e.g., rhoai-3.5-ea.1)")
    create_parser.add_argument("new_version", help="New version (e.g., rhoai-3.5-ea.2)")

    # Update command
    update_parser = subparsers.add_parser("update", help="Update child task")
    update_parser.add_argument("task_key", help="Task key (e.g., RHOAIENG-12345)")
    update_parser.add_argument("--pr-url", help="PR/MR URL to add as comment")
    update_parser.add_argument("--status", help="New status (e.g., 'In Progress', 'Done')")

    # Get command
    get_parser = subparsers.add_parser("get", help="Get parent and child info")
    get_parser.add_argument("parent_key", help="Parent issue key")

    # Comment command
    comment_parser = subparsers.add_parser("comment", help="Add comment to an issue")
    comment_parser.add_argument("issue_key", help="Issue key (e.g., RHOAIENG-12345)")
    comment_parser.add_argument("comment_text", help="Comment text to add")

    args = parser.parse_args()

    try:
        if args.command == "create":
            create_parent_and_children(args.prev_version, args.new_version)
        elif args.command == "update":
            if not args.pr_url and not args.status:
                print("ERROR: Must provide --pr-url or --status")
                sys.exit(1)
            update_child_task(args.task_key, args.pr_url, args.status)
        elif args.command == "get":
            get_parent_info(args.parent_key)
        elif args.command == "comment":
            add_comment_to_issue(args.issue_key, args.comment_text)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
