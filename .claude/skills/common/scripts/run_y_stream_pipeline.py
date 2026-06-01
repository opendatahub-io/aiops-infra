#!/usr/bin/env python3
"""
RHOAI Y-Stream Release Pipeline Orchestrator

Idempotent orchestration of the complete RHOAI release onboarding pipeline:
1. RBC Release - Create release branch on RHOAI-Build-Config
2. RBC Main - Onboard catalog + Tekton to main branch
3. Konflux - Update konflux-release-data
4. PipelineRun Replicator - Replicate PipelineRuns in konflux-central

Can be run multiple times for the same release - automatically resumes from last completed step.

Usage:
    uv run run_y_stream_pipeline.py <previous_version> <new_version> [--repo-dir DIR] [--dry-run] [--resume STATE_FILE]

Example:
    uv run run_y_stream_pipeline.py rhoai-3.4 rhoai-3.4-ea.5
    uv run run_y_stream_pipeline.py rhoai-3.4 rhoai-3.4-ea.5 --dry-run
    uv run run_y_stream_pipeline.py --resume rhoai-release-rhoai-3.4-ea.5-state.json
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "PyGithub",
#     "requests",
# ]
# ///

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class Colors:
    """ANSI color codes for terminal output"""
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str) -> None:
    """Print a formatted header"""
    print(f"\n{Colors.BLUE}{'═' * 63}{Colors.END}")
    print(f"{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BLUE}{'═' * 63}{Colors.END}\n")


def print_success(text: str) -> None:
    """Print success message"""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_error(text: str) -> None:
    """Print error message"""
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def print_info(text: str) -> None:
    """Print info message"""
    print(f"{Colors.YELLOW}▸ {text}{Colors.END}")


def run_command(cmd: list[str], description: str, cwd: Optional[Path] = None) -> tuple[int, str]:
    """Run a shell command and return exit code and output"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode, result.stdout + result.stderr
    except Exception as e:
        return 1, str(e)


def check_prerequisites() -> bool:
    """Check if all required tools and environment variables are present"""
    print_info("Checking prerequisites...")

    # Check tools
    tools = ["uv", "git", "jq"]
    for tool in tools:
        exit_code, _ = run_command(["which", tool], f"Check {tool}")
        if exit_code != 0:
            print_error(f"Required tool '{tool}' not found in PATH")
            return False

    # Check environment variables
    env_vars = ["GITHUB_TOKEN", "KONFLUX_REPO_TOKEN", "JIRA_API_TOKEN"]
    for var in env_vars:
        if not os.getenv(var):
            print_error(f"Required environment variable '{var}' not set")
            return False

    print_success("All prerequisites satisfied")
    return True


def create_or_get_jira(previous_version: str, new_version: str, dry_run: bool) -> dict:
    """Create or retrieve Jira tracking issue"""
    if dry_run:
        print_info("Dry-run mode: Skipping Jira creation")
        return {
            "parent_key": "DRY-RUN",
            "parent_url": "N/A",
            "child_tasks": {
                "rbc_release": "DRY-RUN",
                "rbc_main": "DRY-RUN",
                "konflux": "DRY-RUN",
                "pipelinerun_replicator": "DRY-RUN"
            }
        }

    print_info("Creating Jira tracking issue...")
    script_dir = Path(__file__).parent
    jira_script = script_dir / "rhoai_release_jira.py"

    exit_code, output = run_command(
        ["uv", "run", "--script", str(jira_script), "create", previous_version, new_version],
        "Create Jira"
    )

    if exit_code != 0:
        print_error("Failed to create Jira tracking issue")
        print(output)
        sys.exit(1)

    print(output)

    # Parse Jira state file
    jira_state_file = Path(f"rhoai-release-{new_version}-jira.json")
    if not jira_state_file.exists():
        print_error(f"Jira state file not found: {jira_state_file}")
        sys.exit(1)

    with open(jira_state_file) as f:
        jira_state = json.load(f)

    return {
        "parent_key": jira_state["parent_issue"]["key"],
        "parent_url": jira_state["parent_issue"]["url"],
        "child_tasks": {
            "rbc_release": jira_state["child_tasks"]["rbc_release"]["key"],
            "rbc_main": jira_state["child_tasks"]["rbc_main"]["key"],
            "konflux": jira_state["child_tasks"]["konflux"]["key"],
            "pipelinerun_replicator": jira_state["child_tasks"]["pipelinerun_replicator"]["key"]
        }
    }


def initialize_state(previous_version: str, new_version: str, repo_dir: str, dry_run: bool, jira_info: dict) -> Path:
    """Initialize or load pipeline state file"""
    state_file = Path(f"rhoai-release-{new_version}-state.json")

    if state_file.exists():
        print_info(f"Loading existing state: {state_file}")
        return state_file

    print_info(f"Initializing pipeline state: {state_file}")

    state = {
        "release_info": {
            "previous_version": previous_version,
            "new_version": new_version,
            "konflux_repo_dir": repo_dir,
            "dry_run": dry_run,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        "jira": jira_info,
        "steps": {
            "rbc_release": {
                "status": "pending",
                "pr_url": None,
                "completed_at": None,
                "depends_on": []
            },
            "rbc_main": {
                "status": "pending",
                "pr_url": None,
                "completed_at": None,
                "depends_on": ["rbc_release"]
            },
            "konflux": {
                "status": "pending",
                "mr_url": None,
                "completed_at": None,
                "depends_on": ["rbc_main"]
            },
            "pipelinerun_replicator": {
                "status": "pending",
                "run_url": None,
                "completed_at": None,
                "depends_on": ["konflux"]
            }
        }
    }

    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)

    print_success(f"State initialized: {state_file}")
    print_success(f"Jira parent: {jira_info['parent_url']}")

    return state_file


def load_state(state_file: Path) -> dict:
    """Load state from file"""
    with open(state_file) as f:
        return json.load(f)


def save_state(state_file: Path, state: dict) -> None:
    """Save state to file"""
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def update_jira_status(jira_key: str, status: str, pr_url: Optional[str] = None) -> None:
    """Update Jira task status"""
    if jira_key == "DRY-RUN":
        return

    script_dir = Path(__file__).parent
    jira_script = script_dir / "rhoai_release_jira.py"

    cmd = ["uv", "run", "--script", str(jira_script), "update", jira_key, "--status", status]
    if pr_url:
        cmd.extend(["--pr-url", pr_url])

    run_command(cmd, f"Update Jira {jira_key}")


def execute_step(step_name: str, state_file: Path, state: dict) -> bool:
    """Execute a pipeline step"""
    step = state["steps"][step_name]

    # Check if already done
    if step["status"] == "done":
        url_key = "mr_url" if step_name == "konflux" else ("run_url" if step_name == "pipelinerun_replicator" else "pr_url")
        url = step.get(url_key, "N/A")
        print_success(f"Step {step_name} already completed: {url}")
        return True

    # Check dependencies
    for dep in step.get("depends_on", []):
        dep_status = state["steps"][dep]["status"]
        if dep_status != "done":
            print_info(f"Step {step_name} blocked: waiting for {dep} to complete")
            return False

    # Mark as in progress
    state["steps"][step_name]["status"] = "in_progress"
    save_state(state_file, state)

    # Update Jira to In Progress
    jira_key = state["jira"]["child_tasks"].get(step_name)
    if jira_key:
        update_jira_status(jira_key, "In Progress")

    # Execute the step
    previous_version = state["release_info"]["previous_version"]
    new_version = state["release_info"]["new_version"]
    dry_run = state["release_info"]["dry_run"]
    repo_dir = state["release_info"]["konflux_repo_dir"]

    script_dir = Path(__file__).parent

    step_configs = {
        "rbc_release": {
            "script": "run_rbc_release.py",
            "header": "STEP 1/4: RBC Release",
            "url_pattern": r'https://github\.com/[^/]+/[^/]+/pull/\d+',
            "url_key": "pr_url"
        },
        "rbc_main": {
            "script": "run_rbc_main.py",
            "header": "STEP 2/4: RBC Main Onboard",
            "url_pattern": r'https://github\.com/[^/]+/[^/]+/pull/\d+',
            "url_key": "pr_url"
        },
        "konflux": {
            "script": "run_konflux_onboard.py",
            "header": "STEP 3/4: Konflux Onboard",
            "url_pattern": r'https://gitlab\.[^/]+/[^/]+/[^/]+/-/merge_requests/\d+',
            "url_key": "mr_url"
        },
        "pipelinerun_replicator": {
            "script": "run_pipelinerun_replicator.py",
            "header": "STEP 4/4: PipelineRun Replicator",
            "url_pattern": r'https://github\.com/[^/]+/[^/]+/actions/runs/\d+',
            "url_key": "run_url"
        }
    }

    config = step_configs[step_name]
    print_header(config["header"])

    # Build command
    cmd = ["uv", "run", "--script", str(script_dir / config["script"]), previous_version, new_version]
    if step_name == "konflux":
        cmd.extend(["--repo-dir", repo_dir])
    if dry_run:
        cmd.append("--dry-run")

    # Execute
    exit_code, output = run_command(cmd, f"Execute {step_name}")
    print(output)

    # Extract URL from output
    url_match = re.search(config["url_pattern"], output)
    url = url_match.group(0) if url_match else "N/A"

    # Update state based on result
    if exit_code == 0:
        state["steps"][step_name]["status"] = "done"
        state["steps"][step_name][config["url_key"]] = url
        state["steps"][step_name]["completed_at"] = datetime.now(timezone.utc).isoformat()
        save_state(state_file, state)
        print_success(f"{step_name} completed: {url}")

        # Update Jira to Resolved
        if jira_key:
            update_jira_status(jira_key, "Resolved", url)

        return True
    else:
        state["steps"][step_name]["status"] = "failed"
        save_state(state_file, state)
        print_error(f"{step_name} failed (exit {exit_code})")

        # Update Jira to Failed
        if jira_key:
            update_jira_status(jira_key, "Failed")

        return False


def cleanup_repos(repo_dir: str) -> None:
    """Clean up cloned repositories"""
    print_info("Cleaning up cloned repositories...")

    for repo in ["RHOAI-Build-Config", repo_dir]:
        repo_path = Path(repo)
        if repo_path.exists():
            exit_code, _ = run_command(["rm", "-rf", str(repo_path)], f"Remove {repo}")
            if exit_code == 0:
                print_success(f"Removed {repo}/")


def finalize_pipeline(state_file: Path, state: dict) -> None:
    """Finalize the pipeline and update parent Jira"""
    all_done = all(step["status"] == "done" for step in state["steps"].values())

    if not all_done:
        print_info("\nPipeline paused. Some steps remain:")
        for step_name, step in state["steps"].items():
            if step["status"] != "done":
                print(f"  • {step_name}: {step['status']}")
        print(f"\nTo resume: run the script again")
        print(f"State file: {state_file}")
        return

    # All steps done - update parent Jira
    parent_key = state["jira"]["parent_key"]
    parent_url = state["jira"]["parent_url"]

    if parent_key != "DRY-RUN":
        print_info("Updating parent Jira issue with final summary...")

        jira_comment = f"""Release Onboarding Complete

All automation steps finished successfully.

Previous Version: {state['release_info']['previous_version']}
New Version: {state['release_info']['new_version']}

Pull Requests / Merge Requests / Workflow Runs:
- RBC Release: {state['steps']['rbc_release']['pr_url']}
- RBC Main: {state['steps']['rbc_main']['pr_url']}
- Konflux: {state['steps']['konflux']['mr_url']}
- PipelineRun Replicator: {state['steps']['pipelinerun_replicator']['run_url']}

Next: Review and merge the PRs/MRs, monitor CI/CD pipelines, test builds."""

        update_jira_status(parent_key, "Resolved", jira_comment)
        print_success(f"Jira updated: {parent_url}")

    # Print final summary
    print(f"\n{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BOLD}║      🎉 RHOAI RELEASE ONBOARDING COMPLETE! 🎉               ║{Colors.END}")
    print(f"{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.END}\n")
    print(f"Release: {state['release_info']['previous_version']} → {state['release_info']['new_version']}\n")
    print(f"Jira: {parent_url}\n")
    print("Pull Requests / Merge Requests / Workflow Runs:")
    print(f"  1. RBC Release:           {state['steps']['rbc_release']['pr_url']}")
    print(f"  2. RBC Main:              {state['steps']['rbc_main']['pr_url']}")
    print(f"  3. Konflux MR:            {state['steps']['konflux']['mr_url']}")
    print(f"  4. PipelineRun Workflow:  {state['steps']['pipelinerun_replicator']['run_url']}\n")
    print("Next steps:")
    print("  • Review and merge the PRs/MRs")
    print("  • Monitor CI/CD pipelines")
    print("  • Test the new release builds\n")
    print(f"State file: {state_file}")
    print("═" * 63)

    # Cleanup
    cleanup_repos(state['release_info']['konflux_repo_dir'])


def main():
    parser = argparse.ArgumentParser(
        description="RHOAI Y-Stream Release Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("previous_version", nargs="?", help="Previous RHOAI version (e.g., rhoai-3.4)")
    parser.add_argument("new_version", nargs="?", help="New RHOAI version (e.g., rhoai-3.4-ea.5)")
    parser.add_argument("--repo-dir", default="konflux-release-data", help="Directory for konflux-release-data clone")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without creating PRs/MRs")
    parser.add_argument("--resume", metavar="STATE_FILE", help="Resume from existing state file")

    args = parser.parse_args()

    # Resume mode
    if args.resume:
        state_file = Path(args.resume)
        if not state_file.exists():
            print_error(f"State file not found: {state_file}")
            sys.exit(1)

        state = load_state(state_file)
        previous_version = state["release_info"]["previous_version"]
        new_version = state["release_info"]["new_version"]
        print_info(f"Resuming pipeline: {previous_version} → {new_version}")
    else:
        # New run - validate inputs
        if not args.previous_version or not args.new_version:
            parser.print_help()
            sys.exit(1)

        previous_version = args.previous_version
        new_version = args.new_version

        # Check prerequisites
        if not check_prerequisites():
            sys.exit(1)

        # Create/get Jira
        jira_info = create_or_get_jira(previous_version, new_version, args.dry_run)

        # Initialize state
        state_file = initialize_state(previous_version, new_version, args.repo_dir, args.dry_run, jira_info)
        state = load_state(state_file)

    # Display pipeline summary
    print(f"\n{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BOLD}║          RHOAI RELEASE ONBOARDING PIPELINE                   ║{Colors.END}")
    print(f"{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.END}\n")
    print(f"Previous version: {state['release_info']['previous_version']}")
    print(f"New version:      {state['release_info']['new_version']}")
    print(f"Dry-run mode:     {state['release_info']['dry_run']}\n")
    print("Pipeline Steps:")
    print("  1. RBC Release               → Create release branch (RHOAI-Build-Config)")
    print("  2. RBC Main                  → Onboard to main branch (RHOAI-Build-Config)")
    print("  3. Konflux Onboard           → Update konflux-release-data")
    print("  4. PipelineRun Replicator    → Replicate PipelineRuns in konflux-central\n")
    print(f"State file: {state_file}\n")
    print("═" * 63)

    # Execute steps in order
    steps = ["rbc_release", "rbc_main", "konflux", "pipelinerun_replicator"]
    for step_name in steps:
        if not execute_step(step_name, state_file, state):
            # Step failed or blocked
            state = load_state(state_file)  # Reload state
            if state["steps"][step_name]["status"] == "failed":
                sys.exit(1)
            else:
                # Blocked - stop here
                finalize_pipeline(state_file, state)
                sys.exit(0)

        # Reload state for next iteration
        state = load_state(state_file)

    # All steps completed
    finalize_pipeline(state_file, state)


if __name__ == "__main__":
    main()
