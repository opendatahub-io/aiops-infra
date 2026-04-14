#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "PyGithub>=2.0.0",
#     "requests>=2.28.0",
# ]
# ///
"""
Trigger, monitor, and fetch logs for GitHub Actions workflow runs.

Authentication:
  GITHUB_USER   — required; GitHub username
  GITHUB_TOKEN  — required; personal access token with repo + actions:write scope

Subcommands:
  trigger         Dispatch a workflow_dispatch event; print run ID to stdout.
  monitor         Poll a workflow run to completion; print status to stdout.
  get-step-logs   Download job logs and extract output for a named step.

Usage:
  run_github_workflow.py trigger \\
    --repo-url <url>             # GitHub repo URL (required)
    --workflow <file>            # workflow file path, e.g. .github/workflows/foo.yml
    [--ref <branch>]             # branch/tag/sha to dispatch on (default: main)
    [--input key=value ...]      # workflow inputs (repeatable)

  run_github_workflow.py monitor \\
    --repo-url <url>
    --run-id <id>
    [--timeout <minutes>]        # default: 30
    [--poll-interval <seconds>]  # default: 60

  run_github_workflow.py get-step-logs \\
    --repo-url <url>
    --run-id <id>
    --step <name>                # case-insensitive substring match

trigger output (stdout):
  Single numeric run ID, e.g. 12345678

monitor output (stdout):
  status=<success|failure|cancelled|timeout>

get-step-logs output (stdout):
  Log text of the matching step (stripped of ANSI timestamps).

Exit codes:
  0  Success
  1  Operational error (auth failure, not found, run failed, step not found, timeout)
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from github import Auth, Github, GithubException

POLL_INTERVAL_S = 60  # default seconds between status checks


# ── Auth / helpers ─────────────────────────────────────────────────────────────

def require_env(name: str, hint: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: {name} environment variable is not set.", file=sys.stderr)
        print(f"  {hint}", file=sys.stderr)
        sys.exit(1)
    return value


def parse_repo_path(url: str) -> tuple[str, str]:
    """Extract (owner, repo_name) from a GitHub URL (strips .git suffix)."""
    parsed = urlparse(url)
    path = parsed.path.strip("/").removesuffix(".git")
    parts = path.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        print(f"ERROR: Cannot parse GitHub repo URL: {url}", file=sys.stderr)
        print("  Expected format: https://github.com/<owner>/<repo>", file=sys.stderr)
        sys.exit(1)
    return parts[0], parts[1]


def get_github_client(token: str) -> Github:
    try:
        auth = Auth.Token(token)
        g = Github(auth=auth)
        g.get_user().login  # trigger auth validation
        return g
    except GithubException as exc:
        if exc.status == 401:
            print("ERROR: GitHub authentication failed. Check GITHUB_TOKEN.", file=sys.stderr)
        else:
            print(f"ERROR: GitHub API error during auth: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution", "no route")):
            print("ERROR: Cannot reach GitHub. Check your network connection.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to connect to GitHub: {exc}", file=sys.stderr)
        sys.exit(1)


def get_repo(g: Github, owner: str, repo_name: str):
    try:
        return g.get_repo(f"{owner}/{repo_name}")
    except GithubException as exc:
        if exc.status == 404:
            print(f"ERROR: Repository not found: {owner}/{repo_name}", file=sys.stderr)
            print("  Check the URL and GITHUB_TOKEN permissions (needs repo scope).", file=sys.stderr)
        elif exc.status == 403:
            print(f"ERROR: Access denied to repository: {owner}/{repo_name}", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch repository {owner}/{repo_name}: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution")):
            print("ERROR: Cannot reach GitHub. Check your network connection.", file=sys.stderr)
        else:
            print(f"ERROR: Unexpected error fetching repo: {exc}", file=sys.stderr)
        sys.exit(1)


def strip_log_timestamps(line: str) -> str:
    """Strip GitHub Actions log timestamp prefix: '2024-01-15T10:30:00.1234567Z '"""
    return re.sub(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ", "", line)


# ── Subcommand: trigger ────────────────────────────────────────────────────────

def cmd_trigger(args, token: str) -> None:
    owner, repo_name = parse_repo_path(args.repo_url)

    print(f"Connecting to GitHub...", file=sys.stderr)
    g = get_github_client(token)
    repo = get_repo(g, owner, repo_name)

    # Find workflow by file path
    workflow_file = args.workflow
    # Remove leading ./ or / if present
    workflow_file = workflow_file.lstrip("./")
    # Normalize: ensure no leading slash
    workflow_file = workflow_file.lstrip("/")

    print(f"Looking up workflow: {workflow_file}", file=sys.stderr)
    target_workflow = None
    try:
        workflows = repo.get_workflows()
        for wf in workflows:
            # wf.path is e.g. ".github/workflows/foo.yml"
            wf_path_normalized = wf.path.lstrip("./").lstrip("/")
            # Match on the filename or the full path (normalized)
            if (wf_path_normalized == workflow_file
                    or wf_path_normalized.endswith("/" + workflow_file.split("/")[-1])):
                target_workflow = wf
                break
    except GithubException as exc:
        print(f"ERROR: Failed to list workflows: {exc}", file=sys.stderr)
        sys.exit(1)

    if target_workflow is None:
        print(f"ERROR: Workflow not found: {args.workflow}", file=sys.stderr)
        print(f"  Repo: {owner}/{repo_name}", file=sys.stderr)
        print("  Available workflows:", file=sys.stderr)
        try:
            for wf in repo.get_workflows():
                print(f"    - {wf.path}", file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)

    print(f"Found workflow: {target_workflow.name} ({target_workflow.path})", file=sys.stderr)

    # Parse inputs from key=value pairs
    inputs_dict: dict[str, str] = {}
    for item in args.input:
        if "=" not in item:
            print(f"ERROR: --input must be key=value, got: {item!r}", file=sys.stderr)
            sys.exit(1)
        k, _, v = item.partition("=")
        inputs_dict[k.strip()] = v.strip()

    ref = args.ref or repo.default_branch
    print(f"Dispatching workflow on ref: {ref}", file=sys.stderr)
    if inputs_dict:
        print(f"Inputs: {inputs_dict}", file=sys.stderr)

    # Record time just before dispatch (with 5 s buffer for clock skew)
    before_dt = datetime.now(timezone.utc) - timedelta(seconds=5)

    try:
        target_workflow.create_dispatch(ref=ref, inputs=inputs_dict)
    except GithubException as exc:
        if exc.status == 422:
            print(f"ERROR: Workflow dispatch failed (HTTP 422).", file=sys.stderr)
            data = getattr(exc, "data", {}) or {}
            msg = data.get("message", "")
            if "inputs" in str(msg).lower() or "inputs" in str(data).lower():
                print(
                    "  The workflow rejected the provided inputs. This often means a\n"
                    "  'type: choice' input value is not in the allowed options list.\n"
                    "  Ensure the component is listed in the workflow's options before dispatching.",
                    file=sys.stderr,
                )
            else:
                print(f"  Details: {data}", file=sys.stderr)
        elif exc.status == 403:
            print(
                "ERROR: Permission denied dispatching workflow (HTTP 403).\n"
                "  GITHUB_TOKEN needs 'actions:write' scope (or the legacy 'workflow' scope).",
                file=sys.stderr,
            )
        elif exc.status == 404:
            print(
                f"ERROR: Workflow not found or ref '{ref}' does not exist (HTTP 404).",
                file=sys.stderr,
            )
        else:
            print(f"ERROR: Failed to dispatch workflow: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: Unexpected error dispatching workflow: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Workflow dispatched. Waiting for run to appear...", file=sys.stderr)

    # Poll for the new run (up to 60 s)
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(5)
        try:
            runs = target_workflow.get_runs()
            for run in runs:
                # GitHub returns runs newest-first; stop scanning after runs that
                # are clearly older than our dispatch time
                run_created = run.created_at
                if run_created.tzinfo is None:
                    run_created = run_created.replace(tzinfo=timezone.utc)
                if run_created < before_dt:
                    break
                print(f"  Found candidate run #{run.id} created at {run.created_at}", file=sys.stderr)
                print(run.id)
                sys.exit(0)
        except GithubException as exc:
            print(f"  WARNING: Could not list workflow runs: {exc}", file=sys.stderr)

    print(
        "ERROR: No workflow run appeared within 60 seconds after dispatch.\n"
        "  The workflow may still start — check the Actions tab in the GitHub UI.\n"
        f"  URL: https://github.com/{owner}/{repo_name}/actions/workflows/{target_workflow.path.split('/')[-1]}",
        file=sys.stderr,
    )
    sys.exit(1)


# ── Subcommand: monitor ────────────────────────────────────────────────────────

def cmd_monitor(args, token: str) -> None:
    owner, repo_name = parse_repo_path(args.repo_url)
    run_id = args.run_id
    timeout_minutes = args.timeout
    poll_interval = args.poll_interval

    print(f"Connecting to GitHub...", file=sys.stderr)
    g = get_github_client(token)
    repo = get_repo(g, owner, repo_name)

    print(f"Monitoring workflow run #{run_id} (timeout={timeout_minutes}m, poll={poll_interval}s)...", file=sys.stderr)

    deadline = time.time() + timeout_minutes * 60
    iteration = 0

    while time.time() < deadline:
        if iteration > 0:
            time.sleep(poll_interval)

        iteration += 1
        elapsed_min = int((time.time() - (deadline - timeout_minutes * 60)) / 60)
        remaining_min = max(0, int((deadline - time.time()) / 60))

        try:
            run = repo.get_workflow_run(run_id)
        except GithubException as exc:
            if exc.status == 404:
                print(f"ERROR: Workflow run #{run_id} not found in {owner}/{repo_name}.", file=sys.stderr)
                sys.exit(1)
            print(f"  WARNING: Could not fetch run status: {exc}", file=sys.stderr)
            continue
        except Exception as exc:
            print(f"  WARNING: Unexpected error fetching run status: {exc}", file=sys.stderr)
            continue

        status = run.status or "unknown"
        conclusion = run.conclusion or ""

        if status == "completed":
            status_map = {
                "success": ("status=success", 0),
                "failure": ("status=failure", 1),
                "cancelled": ("status=cancelled", 1),
                "skipped": ("status=skipped", 1),
                "timed_out": ("status=timed_out", 1),
                "action_required": ("status=action_required", 1),
                "neutral": ("status=success", 0),  # neutral = pass
            }
            text, code = status_map.get(conclusion, (f"status={conclusion}", 1))
            print(
                f"[INFO] Run #{run_id} completed: conclusion={conclusion}",
                file=sys.stderr,
            )
            print(
                f"  URL: https://github.com/{owner}/{repo_name}/actions/runs/{run_id}",
                file=sys.stderr,
            )
            print(text)
            sys.exit(code)

        print(
            f"[INFO] Run #{run_id} {status} "
            f"(elapsed={elapsed_min}m, remaining={remaining_min}m). "
            f"Next check in {poll_interval}s...",
            file=sys.stderr,
        )

    print(
        f"[ERROR] Timeout: run #{run_id} still {run.status or 'unknown'} after {timeout_minutes} minutes.",
        file=sys.stderr,
    )
    print(
        f"  URL: https://github.com/{owner}/{repo_name}/actions/runs/{run_id}",
        file=sys.stderr,
    )
    print("status=timeout")
    sys.exit(1)


# ── Subcommand: get-step-logs ──────────────────────────────────────────────────

def cmd_get_step_logs(args, token: str) -> None:
    owner, repo_name = parse_repo_path(args.repo_url)
    run_id = args.run_id
    step_name = args.step

    print(f"Connecting to GitHub...", file=sys.stderr)
    g = get_github_client(token)
    repo = get_repo(g, owner, repo_name)

    # Fetch the run to verify it exists
    try:
        run = repo.get_workflow_run(run_id)
    except GithubException as exc:
        if exc.status == 404:
            print(f"ERROR: Workflow run #{run_id} not found.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch run #{run_id}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Searching for step matching: '{step_name}'", file=sys.stderr)

    # Find the job containing the matching step
    matched_job = None
    matched_step_name = None
    try:
        jobs = list(run.jobs())
    except GithubException as exc:
        print(f"ERROR: Failed to fetch jobs for run #{run_id}: {exc}", file=sys.stderr)
        sys.exit(1)

    for job in jobs:
        for step in job.steps:
            if step_name.lower() in step.name.lower():
                matched_job = job
                matched_step_name = step.name
                break
        if matched_job:
            break

    if matched_job is None:
        print(f"ERROR: No step matching '{step_name}' found in run #{run_id}.", file=sys.stderr)
        print("  Available jobs and steps:", file=sys.stderr)
        for job in jobs:
            print(f"    Job: {job.name}", file=sys.stderr)
            for step in job.steps:
                print(f"      Step: {step.name}", file=sys.stderr)
        sys.exit(1)

    print(f"Found step '{matched_step_name}' in job '{matched_job.name}'.", file=sys.stderr)

    # Download job logs via GitHub API (returns redirect to log text)
    logs_api_url = (
        f"https://api.github.com/repos/{owner}/{repo_name}"
        f"/actions/jobs/{matched_job.id}/logs"
    )
    print(f"Downloading job logs...", file=sys.stderr)

    try:
        resp = requests.get(
            logs_api_url,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            },
            allow_redirects=True,
            timeout=60,
        )
        resp.raise_for_status()
        log_text = resp.text
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "?"
        if status_code == 410:
            print(
                "ERROR: Job logs are no longer available (HTTP 410). "
                "GitHub retains logs for 90 days.",
                file=sys.stderr,
            )
        elif status_code == 403:
            print(
                "ERROR: Permission denied fetching logs (HTTP 403). "
                "Check GITHUB_TOKEN scope.",
                file=sys.stderr,
            )
        else:
            print(f"ERROR: Failed to download job logs (HTTP {status_code}): {exc}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as exc:
        print(f"ERROR: Network error downloading job logs: {exc}", file=sys.stderr)
        sys.exit(1)

    # Parse the log to extract the named step's section.
    # GitHub Actions log format:
    #   2024-01-15T10:30:00.0000000Z ##[group]Run step name
    #   2024-01-15T10:30:00.1000000Z log line
    #   ...
    #   2024-01-15T10:30:01.0000000Z ##[endgroup]
    #
    # We extract lines between the matching ##[group] and the next ##[endgroup].

    lines = log_text.splitlines()
    section_lines: list[str] = []
    in_section = False
    found_section = False

    for line in lines:
        clean = strip_log_timestamps(line)

        if not in_section:
            # Look for group start matching our step name
            if re.search(r"##\[group\]", clean, re.IGNORECASE):
                group_name = re.sub(r"##\[group\]", "", clean, flags=re.IGNORECASE).strip()
                if step_name.lower() in group_name.lower():
                    in_section = True
                    found_section = True
                    continue  # skip the ##[group] line itself
        else:
            if "##[endgroup]" in clean:
                in_section = False
                break  # we have the full section
            section_lines.append(clean)

    if not found_section:
        # Fallback: section markers not found — print entire job log with a warning
        print(
            f"WARNING: Could not locate '##[group]{step_name}' section markers in the log.\n"
            "  Printing full job log instead. Search manually for the step output.",
            file=sys.stderr,
        )
        for line in lines:
            print(strip_log_timestamps(line))
        return

    print(f"--- Step log: {matched_step_name} ---", file=sys.stderr)
    print("\n".join(section_lines))


# ── Main ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")
    sub.required = True

    # ── trigger ────────────────────────────────────────────────────────────────
    p_trigger = sub.add_parser("trigger", help="Dispatch a workflow_dispatch event")
    p_trigger.add_argument("--repo-url",  required=True, metavar="URL",  help="GitHub repo URL")
    p_trigger.add_argument("--workflow",  required=True, metavar="FILE", help="Workflow file path")
    p_trigger.add_argument("--ref",       default=None,  metavar="REF",  help="Branch/tag/sha (default: repo default branch)")
    p_trigger.add_argument("--input",     default=[],    metavar="K=V",  action="append",
                           help="Workflow input as key=value (repeatable)")

    # ── monitor ────────────────────────────────────────────────────────────────
    p_monitor = sub.add_parser("monitor", help="Poll a workflow run to completion")
    p_monitor.add_argument("--repo-url",      required=True, metavar="URL",     help="GitHub repo URL")
    p_monitor.add_argument("--run-id",        required=True, metavar="ID",      type=int, help="Workflow run ID")
    p_monitor.add_argument("--timeout",       default=30,    metavar="MINUTES", type=int, help="Timeout in minutes (default: 30)")
    p_monitor.add_argument("--poll-interval", default=60,    metavar="SECONDS", type=int, help="Poll interval in seconds (default: 60)")

    # ── get-step-logs ──────────────────────────────────────────────────────────
    p_logs = sub.add_parser("get-step-logs", help="Extract logs for a named step")
    p_logs.add_argument("--repo-url", required=True, metavar="URL",  help="GitHub repo URL")
    p_logs.add_argument("--run-id",   required=True, metavar="ID",   type=int, help="Workflow run ID")
    p_logs.add_argument("--step",     required=True, metavar="NAME", help="Step name (case-insensitive substring match)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    _github_user = require_env("GITHUB_USER", "export GITHUB_USER=yourusername")
    github_token = require_env(
        "GITHUB_TOKEN",
        "export GITHUB_TOKEN=yourtoken  # needs: repo + actions:write scope",
    )

    if args.subcommand == "trigger":
        cmd_trigger(args, github_token)
    elif args.subcommand == "monitor":
        cmd_monitor(args, github_token)
    elif args.subcommand == "get-step-logs":
        cmd_get_step_logs(args, github_token)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
