#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "python-dotenv>=1.0.0",
#     "PyGithub>=2.1.0",
# ]
# ///
"""
Trigger Apply Z-Stream Changes GitHub Actions Workflow

Triggers the apply-z-stream-changes workflow in konflux-central repository
to apply z-stream changes from one RHOAI version to another.

Usage:
  run_apply_z_stream_changes.py <prev_version> <new_version> [--dry-run]

Examples:
  run_apply_z_stream_changes.py 3.4.1 3.4.2
  run_apply_z_stream_changes.py 3.4.0-ea.1 3.4.1-ea.1 --dry-run

Environment:
  GITHUB_TOKEN - GitHub personal access token with workflow permissions
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from github import Github

# Load environment
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = "red-hat-data-services"
REPO_NAME = "konflux-central"
WORKFLOW_FILE = "apply-z-stream-changes.yml"


def extract_target_branch(version: str) -> str:
    """
    Extract target branch from version.

    Examples:
        3.4.1 -> rhoai-3.4
        3.4.0-ea.1 -> rhoai-3.4-ea.1
        rhoai-3.4.2 -> rhoai-3.4
        rhoai-3.4.1-ea.1 -> rhoai-3.4-ea.1
    """
    # Remove prefixes
    clean = version.replace("rhoai-", "").replace("v", "")

    # Split into base and suffix
    if "-" in clean:
        base, suffix = clean.split("-", 1)
    else:
        base, suffix = clean, None

    # Extract MAJOR.MINOR from base (drop patch)
    parts = base.split(".")
    target_branch = f"rhoai-{parts[0]}.{parts[1]}" if len(parts) >= 2 else f"rhoai-{base}"

    # Add suffix if present
    if suffix:
        target_branch = f"{target_branch}-{suffix}"

    return target_branch


def extract_rhoai_version(version: str) -> str:
    """
    Extract RHOAI version without prefix.

    Examples:
        3.4.1 -> 3.4.1
        rhoai-3.4.1 -> 3.4.1
        3.4.0-ea.1 -> 3.4.0-ea.1
    """
    return version.replace("rhoai-", "").replace("v", "")


def trigger_workflow(prev_version: str, new_version: str, dry_run: bool = False):
    """Trigger the apply-z-stream-changes GitHub Actions workflow."""

    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN environment variable not set")

    # Extract parameters
    target_branch = extract_target_branch(new_version)
    rhoai_version = extract_rhoai_version(new_version)

    print(f"Triggering Apply Z-Stream Changes workflow...")
    print(f"  Repository: {REPO_OWNER}/{REPO_NAME}")
    print(f"  Workflow: {WORKFLOW_FILE}")
    print(f"  Target branch: {target_branch}")
    print(f"  RHOAI version: {rhoai_version}")
    print(f"  Dry-run: {dry_run}")
    print()

    if dry_run:
        print("⚠ Dry-run mode: Would trigger workflow with:")
        print(f"  target_branch: {target_branch}")
        print(f"  rhoai_version: {rhoai_version}")
        print()
        print("✓ Dry-run completed")
        return None

    # Initialize GitHub client
    gh = Github(GITHUB_TOKEN)
    repo = gh.get_repo(f"{REPO_OWNER}/{REPO_NAME}")

    # Get the workflow
    workflow = repo.get_workflow(WORKFLOW_FILE)

    # Trigger workflow on main branch
    success = workflow.create_dispatch(
        ref="main",
        inputs={
            "target_branch": target_branch,
            "rhoai_version": rhoai_version
        }
    )

    if not success:
        raise Exception("Failed to trigger workflow")

    print("✓ Workflow triggered successfully")
    print()

    # Wait a moment for the workflow run to appear
    print("Waiting for workflow run to start...")
    time.sleep(5)

    # Get the latest workflow run
    runs = workflow.get_runs()
    if runs.totalCount > 0:
        latest_run = runs[0]
        run_url = latest_run.html_url
        print(f"✓ Workflow run started: {run_url}")
        print()
        print(f"Run URL: {run_url}")
        return run_url
    else:
        print("⚠ Could not find workflow run (it may still be starting)")
        print(f"Check: https://github.com/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{WORKFLOW_FILE}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Trigger Apply Z-Stream Changes workflow"
    )
    parser.add_argument(
        "prev_version",
        help="Previous RHOAI z-stream version (e.g., 3.4.1)"
    )
    parser.add_argument(
        "new_version",
        help="New RHOAI z-stream version (e.g., 3.4.2)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the workflow trigger without actually triggering it"
    )

    args = parser.parse_args()

    try:
        run_url = trigger_workflow(args.prev_version, args.new_version, args.dry_run)
        if run_url:
            print()
            print("="*60)
            print("Next steps:")
            print(f"  1. Monitor the workflow run: {run_url}")
            print(f"  2. Verify z-stream changes were applied correctly")
            print(f"  3. Check for any failures or warnings")
            print("="*60)
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
