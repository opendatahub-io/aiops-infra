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
    uv run run_y_stream_pipeline.py <previous_version> <new_version> [--repo-dir DIR] [--jira-url URL] [--dry-run] [--resume STATE_FILE]

Example:
    uv run run_y_stream_pipeline.py rhoai-3.4 rhoai-3.4-ea.5
    uv run run_y_stream_pipeline.py rhoai-3.4 rhoai-3.4-ea.5 --jira-url https://issues.redhat.com/browse/RHOAIENG-1234
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


def display_jira_info(state: dict) -> None:
    """Display Jira tracking information prominently"""
    jira_info = state["jira"]
    release_info = state["release_info"]

    if jira_info["parent_key"] == "DRY-RUN":
        print(f"\n{Colors.YELLOW}  ⚠  Dry-run mode — Jira tracking disabled{Colors.END}\n")
        return

    prev = release_info["previous_version"]
    new = release_info["new_version"]

    print(f"\n{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BOLD}║             📋 JIRA TRACKING INFORMATION                     ║{Colors.END}")
    print(f"{Colors.BOLD}╠══════════════════════════════════════════════════════════════╣{Colors.END}")
    print(f"{Colors.BOLD}║{Colors.END}  Parent Issue:                                               {Colors.BOLD}║{Colors.END}")
    print(f"{Colors.BOLD}║{Colors.END}    {Colors.BLUE}{jira_info['parent_url']}{Colors.END}")
    print(f"{Colors.BOLD}║{Colors.END}    {jira_info['parent_key']}: Release Onboarding {prev} → {new}")
    print(f"{Colors.BOLD}║{Colors.END}                                                              {Colors.BOLD}║{Colors.END}")
    print(f"{Colors.BOLD}║{Colors.END}  Child Tasks:                                                {Colors.BOLD}║{Colors.END}")
    child_tasks = jira_info["child_tasks"]
    print(f"{Colors.BOLD}║{Colors.END}    1. {child_tasks.get('rbc_release', 'N/A'):15} — RBC Release")
    print(f"{Colors.BOLD}║{Colors.END}    2. {child_tasks.get('rbc_main', 'N/A'):15} — RBC Main")
    print(f"{Colors.BOLD}║{Colors.END}    3. {child_tasks.get('konflux', 'N/A'):15} — Konflux")
    print(f"{Colors.BOLD}║{Colors.END}    4. {child_tasks.get('pipelinerun_replicator', 'N/A'):15} — PipelineRun Replicator")
    print(f"{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.END}\n")


def _step_url(step_data: dict, step_name: str) -> Optional[str]:
    """Extract the PR/MR/run URL from a step's state"""
    for key in ("pr_url", "mr_url", "run_url"):
        url = step_data.get(key)
        if url and url != "N/A":
            return url
    return None


def print_progress_tracker(state: dict) -> None:
    """Print a dashboard-style progress tracker with live status and URLs"""
    step_meta = [
        ("rbc_release",           "RBC Release",           "1"),
        ("rbc_main",              "RBC Main",              "2"),
        ("konflux",               "Konflux",               "3"),
        ("pipelinerun_replicator","PipelineRun Replicator", "4"),
    ]

    total = len(step_meta)
    done_count = sum(1 for k, _, _ in step_meta if state["steps"][k]["status"] == "done")

    bar_filled = int((done_count / total) * 20)
    bar_empty = 20 - bar_filled
    progress_bar = f"{'█' * bar_filled}{'░' * bar_empty}"

    print(f"\n{Colors.BOLD}┌──────────────────────────────────────────────────────────────┐{Colors.END}")
    print(f"{Colors.BOLD}│               PIPELINE PROGRESS  [{done_count}/{total}]                         │{Colors.END}")
    print(f"{Colors.BOLD}│  {Colors.GREEN}{progress_bar}{Colors.END}  {done_count}/{total} steps complete{' ' * 18}{Colors.BOLD}│{Colors.END}")
    print(f"{Colors.BOLD}├──────────────────────────────────────────────────────────────┤{Colors.END}")

    for step_key, label, num in step_meta:
        step = state["steps"][step_key]
        status = step["status"]
        url = _step_url(step, step_key)

        if status == "done":
            icon = f"{Colors.GREEN}✓{Colors.END}"
            status_text = f"{Colors.GREEN}Completed{Colors.END}"
        elif status == "in_progress":
            icon = f"{Colors.BLUE}▶{Colors.END}"
            status_text = f"{Colors.BLUE}Running...{Colors.END}"
        elif status == "failed":
            icon = f"{Colors.RED}✗{Colors.END}"
            status_text = f"{Colors.RED}Failed{Colors.END}"
        else:
            icon = f"○"
            status_text = "Pending"

        print(f"{Colors.BOLD}│{Colors.END}  {icon} {num}. {label:28} {status_text}")
        if url and status == "done":
            print(f"{Colors.BOLD}│{Colors.END}       └─ {Colors.BLUE}{url}{Colors.END}")

    print(f"{Colors.BOLD}└──────────────────────────────────────────────────────────────┘{Colors.END}\n")


def run_command(cmd: list[str], description: str, cwd: Optional[Path] = None, stream: bool = True) -> tuple[int, str]:
    """Run a shell command and return exit code and output

    Args:
        cmd: Command to run as list
        description: Description for logging
        cwd: Working directory
        stream: If True, stream output in real-time. If False, capture and return.
    """
    try:
        if stream:
            # Stream output in real-time
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            output_lines = []
            for line in process.stdout:
                print(line, end='', flush=True)
                output_lines.append(line)

            process.wait()
            return process.returncode, ''.join(output_lines)
        else:
            # Capture output (for Jira updates, etc.)
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


def create_or_get_jira(previous_version: str, new_version: str, dry_run: bool, jira_url: Optional[str] = None) -> dict:
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

    script_dir = Path(__file__).parent
    jira_script = script_dir / "rhoai_release_jira.py"

    # Use existing Jira if URL provided
    if jira_url:
        print_info(f"Using existing Jira issue: {jira_url}")

        exit_code, output = run_command(
            ["uv", "run", "--script", str(jira_script), "get", jira_url, new_version],
            "Get Jira"
        )

        if exit_code != 0:
            print_error("Failed to retrieve existing Jira tracking issue")
            print(output)
            sys.exit(1)

        print(output)
    else:
        # Create new Jira
        print_info("Creating Jira tracking issue...")

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


def execute_step(step_name: str, state_file: Path, state: dict) -> tuple[bool, bool]:
    """Execute a pipeline step.

    Returns (success, was_executed) where was_executed is False if step was already done.
    """
    step = state["steps"][step_name]

    # Check if already done
    if step["status"] == "done":
        url_key = "mr_url" if step_name == "konflux" else ("run_url" if step_name == "pipelinerun_replicator" else "pr_url")
        url = step.get(url_key, "N/A")
        print_success(f"Step {step_name} already completed: {url}")
        return True, False

    # Check dependencies
    for dep in step.get("depends_on", []):
        dep_status = state["steps"][dep]["status"]
        if dep_status != "done":
            print_info(f"Step {step_name} blocked: waiting for {dep} to complete")
            return False, False

    # Show progress tracker before starting step
    print_progress_tracker(state)

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

    # Clear step start banner
    print(f"\n{Colors.BOLD}{Colors.BLUE}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}║  ▶  {config['header']:55} ║{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}╚══════════════════════════════════════════════════════════════╝{Colors.END}")
    print(f"{Colors.YELLOW}  Release: {previous_version} → {new_version}{Colors.END}")
    if jira_key and jira_key != "DRY-RUN":
        print(f"{Colors.YELLOW}  Jira:    {jira_key}{Colors.END}")
    print()

    # Build command
    cmd = ["uv", "run", "--script", str(script_dir / config["script"]), previous_version, new_version]
    if step_name == "konflux":
        cmd.extend(["--repo-dir", repo_dir])
    if dry_run:
        cmd.append("--dry-run")

    # Execute with real-time streaming
    print(f"{Colors.BLUE}{'─' * 63}{Colors.END}")
    print(f"{Colors.BLUE}  ▶ Running {config['header'].split(':')[1].strip()}...{Colors.END}")
    print(f"{Colors.BLUE}{'─' * 63}{Colors.END}\n")
    exit_code, output = run_command(cmd, f"Execute {step_name}", stream=True)
    print(f"\n{Colors.BLUE}{'─' * 63}{Colors.END}")

    # Extract URL from output
    url_match = re.search(config["url_pattern"], output)
    url = url_match.group(0) if url_match else "N/A"

    # Update state based on result
    if exit_code == 0:
        state["steps"][step_name]["status"] = "done"
        state["steps"][step_name][config["url_key"]] = url
        state["steps"][step_name]["completed_at"] = datetime.now(timezone.utc).isoformat()
        save_state(state_file, state)

        # Clear completion banner
        done_text = f"  ✓  {config['header']}"
        print(f"\n{Colors.GREEN}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
        print(f"{Colors.GREEN}║{done_text:62}║{Colors.END}")
        print(f"{Colors.GREEN}╚══════════════════════════════════════════════════════════════╝{Colors.END}")
        if url and url != "N/A":
            print(f"{Colors.GREEN}  └─ {url}{Colors.END}")

        # Show updated dashboard
        print_progress_tracker(state)

        # Update Jira to Resolved
        if jira_key:
            update_jira_status(jira_key, "Resolved", url)

        return True, True
    else:
        state["steps"][step_name]["status"] = "failed"
        save_state(state_file, state)

        # Clear failure banner
        fail_text = f"  ✗  {config['header']} — FAILED (exit {exit_code})"
        print(f"\n{Colors.RED}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
        print(f"{Colors.RED}║{fail_text:62}║{Colors.END}")
        print(f"{Colors.RED}╚══════════════════════════════════════════════════════════════╝{Colors.END}")

        # Show updated dashboard
        print_progress_tracker(state)

        # Update Jira to Failed
        if jira_key:
            update_jira_status(jira_key, "Failed")

        return False, True


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

    # All steps done - add comment to parent Jira (but don't resolve it)
    parent_key = state["jira"]["parent_key"]
    parent_url = state["jira"]["parent_url"]

    if parent_key != "DRY-RUN":
        print_info("Adding completion comment to parent Jira issue with all PR/MR details...")

        prev = state['release_info']['previous_version']
        new = state['release_info']['new_version']
        rbc_release_pr = state['steps']['rbc_release'].get('pr_url', 'N/A')
        rbc_main_pr = state['steps']['rbc_main'].get('pr_url', 'N/A')
        konflux_mr = state['steps']['konflux'].get('mr_url', 'N/A')
        replicator_run = state['steps']['pipelinerun_replicator'].get('run_url', 'N/A')
        child_tasks = state['jira']['child_tasks']

        jira_comment = (
            f"h2. Release Onboarding Complete\n\n"
            f"All automation steps finished successfully.\n\n"
            f"||Property||Value||\n"
            f"|Previous Version|{{{{{prev}}}}}|\n"
            f"|New Version|{{{{{new}}}}}|\n\n"
            f"----\n\n"
            f"h3. Pull Requests / Merge Requests\n\n"
            f"||#||Step||Status||PR / MR||Subtask||\n"
            f"|1|RBC Release Branch|(/) Completed|[{rbc_release_pr}]|{child_tasks.get('rbc_release', 'N/A')}|\n"
            f"|2|RBC Main Onboard|(/) Completed|[{rbc_main_pr}]|{child_tasks.get('rbc_main', 'N/A')}|\n"
            f"|3|Konflux Release Data|(/) Completed|[{konflux_mr}]|{child_tasks.get('konflux', 'N/A')}|\n"
            f"|4|PipelineRun Replicator|(/) Completed|[{replicator_run}]|{child_tasks.get('pipelinerun_replicator', 'N/A')}|\n\n"
            f"----\n\n"
            f"h3. Next Steps\n\n"
            f"# Review and merge all PRs/MRs\n"
            f"# Monitor CI/CD pipeline execution\n"
            f"# Verify builds are successful\n"
            f"# Test the new release artifacts\n"
            f"# Manually close this Jira when all verification is complete\n\n"
            f"{{panel:title=Important|borderStyle=solid|borderColor=#ffab00|titleBGColor=#fff0b3|bgColor=#fffae6}}\n"
            f"Please review all automation results and manually close this issue after verification.\n"
            f"{{panel}}"
        )

        script_dir = Path(__file__).parent
        jira_script = script_dir / "rhoai_release_jira.py"
        exit_code, _ = run_command(
            ["uv", "run", "--script", str(jira_script), "comment", parent_key, jira_comment],
            "Add Jira comment",
            stream=False
        )
        if exit_code == 0:
            print_success(f"Jira comment added with all PR/MR details: {parent_url}")
        else:
            print_error(f"Failed to add Jira comment — update {parent_key} manually")

    # ── Final summary ────────────────────────────────────────────
    print(f"\n{Colors.BOLD}{Colors.GREEN}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BOLD}{Colors.GREEN}║          RHOAI RELEASE ONBOARDING COMPLETE                   ║{Colors.END}")
    print(f"{Colors.BOLD}{Colors.GREEN}╚══════════════════════════════════════════════════════════════╝{Colors.END}")
    print(f"\n{Colors.BOLD}Release:{Colors.END} {state['release_info']['previous_version']} → {Colors.GREEN}{state['release_info']['new_version']}{Colors.END}\n")

    # Reuse the shared Jira display
    display_jira_info(state)

    # Final progress dashboard shows all URLs
    print_progress_tracker(state)

    # Jira comment confirmation
    if parent_key != "DRY-RUN":
        print(f"{Colors.GREEN}  A summary comment with all PR/MR links has been posted to:{Colors.END}")
        print(f"  {Colors.BLUE}{parent_url}{Colors.END}\n")

    # Next steps
    print(f"{Colors.BOLD}┌──────────────────────────────────────────────────────────────┐{Colors.END}")
    print(f"{Colors.BOLD}│                       NEXT STEPS                             │{Colors.END}")
    print(f"{Colors.BOLD}├──────────────────────────────────────────────────────────────┤{Colors.END}")
    print(f"{Colors.BOLD}│{Colors.END}  1. Review and merge all PRs/MRs                             {Colors.BOLD}│{Colors.END}")
    print(f"{Colors.BOLD}│{Colors.END}  2. Monitor CI/CD pipeline execution                         {Colors.BOLD}│{Colors.END}")
    print(f"{Colors.BOLD}│{Colors.END}  3. Verify builds are successful                             {Colors.BOLD}│{Colors.END}")
    print(f"{Colors.BOLD}│{Colors.END}  4. Test the new release artifacts                           {Colors.BOLD}│{Colors.END}")
    if parent_key != "DRY-RUN":
        print(f"{Colors.BOLD}│{Colors.END}  5. {Colors.YELLOW}Manually close the Jira issue when verified{Colors.END}              {Colors.BOLD}│{Colors.END}")
    print(f"{Colors.BOLD}└──────────────────────────────────────────────────────────────┘{Colors.END}")
    print(f"\n  State file: {state_file}")
    print(f"{'═' * 63}")

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
    parser.add_argument("--jira-url", help="Use existing Jira issue URL instead of creating a new one")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without creating PRs/MRs")
    parser.add_argument("--resume", metavar="STATE_FILE", help="Resume from existing state file")
    parser.add_argument("--single-step", action="store_true",
                        help="Run at most one pending step then exit (for agent-driven progress display)")

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
        jira_info = create_or_get_jira(previous_version, new_version, args.dry_run, args.jira_url)

        # Initialize state
        state_file = initialize_state(previous_version, new_version, args.repo_dir, args.dry_run, jira_info)
        state = load_state(state_file)

    # Display pipeline summary
    print(f"\n{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BOLD}║          RHOAI RELEASE ONBOARDING PIPELINE                   ║{Colors.END}")
    print(f"{Colors.BOLD}╠══════════════════════════════════════════════════════════════╣{Colors.END}")
    print(f"{Colors.BOLD}║{Colors.END}  Previous version: {state['release_info']['previous_version']}")
    print(f"{Colors.BOLD}║{Colors.END}  New version:      {Colors.GREEN}{state['release_info']['new_version']}{Colors.END}")
    if state['release_info']['dry_run']:
        print(f"{Colors.BOLD}║{Colors.END}  Mode:            {Colors.YELLOW}DRY-RUN{Colors.END}")
    print(f"{Colors.BOLD}╠══════════════════════════════════════════════════════════════╣{Colors.END}")
    print(f"{Colors.BOLD}║{Colors.END}  Pipeline Steps:")
    print(f"{Colors.BOLD}║{Colors.END}    1. RBC Release            → Create release branch (RBC)")
    print(f"{Colors.BOLD}║{Colors.END}    2. RBC Main               → Onboard to main branch (RBC)")
    print(f"{Colors.BOLD}║{Colors.END}    3. Konflux Onboard        → Update konflux-release-data")
    print(f"{Colors.BOLD}║{Colors.END}    4. PipelineRun Replicator → Replicate PipelineRuns")
    print(f"{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.END}")
    print(f"  State file: {state_file}")

    # Display Jira tracking info prominently
    display_jira_info(state)

    # Show initial progress dashboard
    print_progress_tracker(state)

    # Execute steps in order
    steps = ["rbc_release", "rbc_main", "konflux", "pipelinerun_replicator"]

    for step_name in steps:
        success, was_executed = execute_step(step_name, state_file, state)

        if not success:
            state = load_state(state_file)
            if state["steps"][step_name]["status"] == "failed":
                sys.exit(1)
            else:
                finalize_pipeline(state_file, state)
                sys.exit(0)

        state = load_state(state_file)

        # In single-step mode, exit only after a step was actually executed (not skipped)
        if args.single_step and was_executed:
            all_done = all(s["status"] == "done" for s in state["steps"].values())
            if all_done:
                finalize_pipeline(state_file, state)
            sys.exit(0)

    # All steps completed (non-single-step mode)
    finalize_pipeline(state_file, state)


if __name__ == "__main__":
    main()
