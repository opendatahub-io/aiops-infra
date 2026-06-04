#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "jira>=3.5.0",
#     "python-dotenv>=1.0.0",
# ]
# ///
"""
RHOAI Z-Stream Release Jira Management

Creates parent issue and child tasks for RHOAI z-stream release onboarding.
Updates child tasks with PR/MR URLs and status.

Usage:
  rhoai_zstream_jira.py create <prev_version> <new_version>
  rhoai_zstream_jira.py update <task_key> --pr-url <url> --status <status>
  rhoai_zstream_jira.py get <parent_key>

Environment:
  JIRA_URL - Jira server URL (default: https://redhat.atlassian.net)
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
    """Create parent issue and 4 child tasks for z-stream."""
    jira = create_jira_client()

    # Create parent issue
    print(f"Creating parent issue in {JIRA_PROJECT}...")
    parent_issue = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"RHOAI Z-Stream Release: {prev_version} → {new_version}",
        description=f"""RHOAI z-stream release onboarding automation tracking.

Previous Version: {prev_version}
New Version: {new_version}

This issue tracks the 4-step z-stream onboarding pipeline:
1. RBC Release - Update release branch on RHOAI-Build-Config
2. RBC Main - Update main branch Tekton fragments
3. Konflux - Update konflux-release-data
4. Apply Z-Stream Changes - Trigger GitHub Actions workflow in konflux-central

Child tasks will be updated with PR/MR/workflow URLs as automation completes.
""",
        issuetype={"name": "Task"},
    )

    parent_key = parent_issue.key
    print(f"✓ Created parent: {parent_key}")

    # Create child tasks
    child_tasks = {}

    # Task 1: RBC Release (Z-Stream)
    print("Creating child task 1: RBC Z-Stream Release...")
    task1 = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"RBC Z-Stream Release: {prev_version} → {new_version}",
        description=f"""Update release branch on RHOAI-Build-Config for z-stream.

- Update TrustyAI PIG config (productVersion)
- Update bundle-patch.yaml version
- Update catalog-patch.yaml channel entries
- Update Tekton files (rhoai-version parameter)
- Create PR to release branch

Previous: {prev_version}
New: {new_version}

Automation: rbc_zstream_release.py
""",
        issuetype={"name": "Sub-task"},
        parent={"key": parent_key},
    )
    child_tasks["rbc_release"] = task1.key
    print(f"✓ Created: {task1.key}")

    # Task 2: RBC Main (Z-Stream)
    print("Creating child task 2: RBC Z-Stream Main...")
    task2 = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"RBC Z-Stream Main: {prev_version} → {new_version}",
        description=f"""Update main branch Tekton fragment pipelines for z-stream.

- Find stage Tekton fragment files for the train
- Update rhoai-version parameter from {prev_version} to {new_version}
- Create PR to main branch

Automation: rbc_zstream_main.py
""",
        issuetype={"name": "Sub-task"},
        parent={"key": parent_key},
    )
    child_tasks["rbc_main"] = task2.key
    print(f"✓ Created: {task2.key}")

    # Task 3: Konflux (Z-Stream)
    print("Creating child task 3: Konflux Z-Stream...")
    task3 = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"Konflux Z-Stream: {prev_version} → {new_version}",
        description=f"""Update konflux-release-data repository for z-stream.

- Locate existing tenant directory (in-place update)
- Update ProdReleasePlans and StageReleasePlans YAML files
- Update version references from {prev_version} to {new_version}
- Run build-manifests.sh
- Create GitLab MR

Automation: konflux_zstream_onboard.py
""",
        issuetype={"name": "Sub-task"},
        parent={"key": parent_key},
    )
    child_tasks["konflux"] = task3.key
    print(f"✓ Created: {task3.key}")

    # Task 4: Apply Z-Stream Changes
    print("Creating child task 4: Apply Z-Stream Changes...")
    task4 = jira.create_issue(
        project=JIRA_PROJECT,
        summary=f"Apply Z-Stream Changes: {prev_version} → {new_version}",
        description=f"""Trigger GitHub Actions workflow to apply z-stream changes in konflux-central.

- Trigger apply-z-stream-changes.yml workflow
- Target branch: rhoai-{new_version.split('.')[0]}.{new_version.split('.')[1] if '.' in new_version else ''}
- RHOAI version: {new_version}
- Monitor workflow execution

Automation: run_apply_z_stream_changes.py
""",
        issuetype={"name": "Sub-task"},
        parent={"key": parent_key},
    )
    child_tasks["apply_z_stream_changes"] = task4.key
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
    state_file = f"rhoai-zstream-{new_version}-jira.json"
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)

    # Print summary
    print("\n" + "="*60)
    print("JIRA TRACKING CREATED (Z-STREAM)")
    print("="*60)
    print(f"\nParent Issue: {state['parent_issue']['url']}")
    print(f"  {parent_key}: RHOAI Z-Stream Release: {prev_version} → {new_version}")
    print("\nChild Tasks:")
    print(f"  1. {state['child_tasks']['rbc_release']['url']}")
    print(f"     {child_tasks['rbc_release']}: RBC Z-Stream Release")
    print(f"\n  2. {state['child_tasks']['rbc_main']['url']}")
    print(f"     {child_tasks['rbc_main']}: RBC Z-Stream Main")
    print(f"\n  3. {state['child_tasks']['konflux']['url']}")
    print(f"     {child_tasks['konflux']}: Konflux Z-Stream")
    print(f"\n  4. {state['child_tasks']['apply_z_stream_changes']['url']}")
    print(f"     {child_tasks['apply_z_stream_changes']}: Apply Z-Stream Changes")
    print(f"\nState saved to: {state_file}")
    print("\nNext: /rhoai-z-stream-onboarding (will auto-update Jira with PR/MR/workflow URLs)")
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
    parser = argparse.ArgumentParser(description="RHOAI Z-Stream Release Jira Management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Create command
    create_parser = subparsers.add_parser("create", help="Create parent and child issues")
    create_parser.add_argument("prev_version", help="Previous z-stream version (e.g., 3.4.1, 3.4.0-ea.1)")
    create_parser.add_argument("new_version", help="New z-stream version (e.g., 3.4.2, 3.4.1-ea.1)")

    # Update command
    update_parser = subparsers.add_parser("update", help="Update child task")
    update_parser.add_argument("task_key", help="Task key (e.g., RHOAIENG-12345)")
    update_parser.add_argument("--pr-url", help="PR/MR URL to add as comment")
    update_parser.add_argument("--status", help="New status (e.g., 'In Progress', 'Done')")

    # Get command
    get_parser = subparsers.add_parser("get", help="Get parent and child info")
    get_parser.add_argument("parent_key", help="Parent issue key")

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
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
