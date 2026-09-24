#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "python-dotenv>=1.0.0",
#     "PyGithub>=2.1.0",
# ]
# ///
"""
Trigger PipelineRun Replicator GitHub Actions Workflow

Triggers the pipelinerun-replicator workflow in konflux-central repository
to replicate PipelineRun configurations from one RHOAI version to another.

Usage:
  run_pipelinerun_replicator.py <prev_version> <new_version> [--dry-run]

Examples:
  run_pipelinerun_replicator.py rhoai-3.5-ea.2 rhoai-3.5-ea.3
  run_pipelinerun_replicator.py rhoai-3.5-ea.2 rhoai-3.5-ea.3 --dry-run

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
WORKFLOW_FILE = "pipelinerun-replicator.yml"


def extract_rhoai_version(version: str) -> str:
    """
    Extract and normalize RHOAI version to MAJOR.MINOR.PATCH[-SUFFIX] format.

    Examples:
        rhoai-3.4 -> 3.4.0
        rhoai-3.4-ea.3 -> 3.4.0-ea.3
        rhoai-3.5.1 -> 3.5.1
        rhoai-3.5.1-ea.2 -> 3.5.1-ea.2
    """
    # Remove prefixes
    clean = version.replace("rhoai-", "").replace("v", "")

    # Split into base and suffix
    if "-" in clean:
        base, suffix = clean.split("-", 1)
    else:
        base, suffix = clean, None

    # Ensure base has 3 parts (MAJOR.MINOR.PATCH)
    parts = base.split(".")
    while len(parts) < 3:
        parts.append("0")
    base = ".".join(parts[:3])

    # Rejoin with suffix if present
    return f"{base}-{suffix}" if suffix else base


def trigger_workflow(prev_version: str, new_version: str, dry_run: bool = False):
    """Trigger the pipelinerun-replicator GitHub Actions workflow."""

    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN environment variable not set")

    # Extract normalized RHOAI version
    rhoai_version = extract_rhoai_version(new_version)

    print(f"Triggering PipelineRun Replicator workflow...")
    print(f"  Repository: {REPO_OWNER}/{REPO_NAME}")
    print(f"  Workflow: {WORKFLOW_FILE}")
    print(f"  Source branch: {prev_version}")
    print(f"  Target branch: {new_version}")
    print(f"  RHOAI version: {rhoai_version}")
    print(f"  Dry-run: {dry_run}")
    print()

    if dry_run:
        print("⚠ Dry-run mode: Would trigger workflow with:")
        print(f"  source_branch: {prev_version}")
        print(f"  target_branch: {new_version}")
        print(f"  rhoai_version: {rhoai_version}")
        print(f"  dry_run: true")
        print()
        print("✓ Dry-run completed")
        return None

    # Initialize GitHub client
    gh = Github(GITHUB_TOKEN)
    repo = gh.get_repo(f"{REPO_OWNER}/{REPO_NAME}")

    # Get the workflow
    workflow = repo.get_workflow(WORKFLOW_FILE)

    # Trigger workflow on main branch with correct parameter names
    success = workflow.create_dispatch(
        ref="main",
        inputs={
            "source_branch": prev_version,
            "target_branch": new_version,
            "rhoai_version": rhoai_version,
            "dry_run": "false"
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
        description="Trigger PipelineRun Replicator workflow"
    )
    parser.add_argument(
        "prev_version",
        help="Previous RHOAI version (e.g., rhoai-3.5-ea.2)"
    )
    parser.add_argument(
        "new_version",
        help="New RHOAI version (e.g., rhoai-3.5-ea.3)"
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
            print(f"  2. Verify PipelineRuns were replicated correctly")
            print(f"  3. Check for any failures or warnings")
            print("="*60)
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
