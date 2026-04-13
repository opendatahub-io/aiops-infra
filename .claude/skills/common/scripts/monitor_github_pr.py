#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "PyGithub>=2.0.0",
# ]
# ///
"""
Monitor a GitHub pull request until it is merged, closed, or times out.

Supports a --check-only mode that prints the current PR state and exits immediately
(used by skills to inspect existing PRs without polling).

Authentication:
  GITHUB_USER   — required; GitHub username
  GITHUB_TOKEN  — required; personal access token with `repo` scope

Usage:
  monitor_github_pr.py \
    --pr-url <url>            # mandatory; full GitHub PR web URL
    [--timeout <minutes>]     # optional; polling timeout in minutes (default: 60)
    [--check-only]            # optional; print state once and exit

Output:

  --check-only mode (stdout):
    state=<open|merged|closed>
    title=<PR title>

  Polling mode:
    Progress lines are written to stderr every 60 seconds.
    On terminal event, one word is written to stdout:
      merged            → PR was merged
      closed            → PR was closed without merging
      pipeline_failed   → CI checks failed on the head commit
      pipeline_canceled → CI checks were cancelled on the head commit
      timeout           → timeout reached while PR still open

Exit codes:
  0  merged (or check-only with a valid response)
  1  closed, pipeline failed/canceled, or timeout
  2  URL parse error, auth failure, repo/PR not found
"""

import argparse
import os
import re
import sys
import time
from urllib.parse import urlparse

from github import Auth, Github, GithubException

POLL_INTERVAL_S = 60  # seconds between status checks

# Check-run conclusions that map to "pipeline failed"
_FAILED_CONCLUSIONS    = {"failure", "timed_out", "action_required"}
_CANCELLED_CONCLUSIONS = {"cancelled"}


def require_env(name: str, hint: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: {name} environment variable is not set.", file=sys.stderr)
        print(f"  {hint}", file=sys.stderr)
        sys.exit(2)
    return value


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    """
    Parse a GitHub PR URL and return (owner, repo, pr_number).

    Expected format: https://github.com/<owner>/<repo>/pull/<number>
    """
    pattern = r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)"
    match = re.match(pattern, pr_url.rstrip("/"))
    if not match:
        print("ERROR: Cannot parse PR URL.", file=sys.stderr)
        print("  Expected format: https://github.com/<owner>/<repo>/pull/<number>", file=sys.stderr)
        print(f"  Got: {pr_url}", file=sys.stderr)
        sys.exit(2)
    return match.group(1), match.group(2), int(match.group(3))


def get_github_client(token: str) -> Github:
    try:
        auth = Auth.Token(token)
        g = Github(auth=auth)
        g.get_user().login  # Trigger auth validation
        return g
    except GithubException as exc:
        if exc.status == 401:
            print("ERROR: GitHub authentication failed. Check GITHUB_TOKEN.", file=sys.stderr)
        else:
            print(f"ERROR: GitHub API error during auth: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution", "no route")):
            print("ERROR: Cannot reach GitHub. Check your network connection.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to connect to GitHub: {exc}", file=sys.stderr)
        sys.exit(2)


def get_repo_and_pr(g: Github, owner: str, repo_name: str, pr_number: int):
    """Fetch the repo and PR objects, exiting with code 2 on any lookup error."""
    try:
        repo = g.get_repo(f"{owner}/{repo_name}")
    except GithubException as exc:
        if exc.status == 404:
            print(f"ERROR: Repository not found: {owner}/{repo_name}", file=sys.stderr)
            print("  Check that the PR URL is correct.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch repository {owner}/{repo_name}: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution")):
            print("ERROR: Cannot reach GitHub. Check your network connection.", file=sys.stderr)
        else:
            print(f"ERROR: Unexpected error fetching repository: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        pr = repo.get_pull(pr_number)
    except GithubException as exc:
        if exc.status == 404:
            print(f"ERROR: PR #{pr_number} not found in {owner}/{repo_name}.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch PR #{pr_number}: {exc}", file=sys.stderr)
        sys.exit(2)

    return repo, pr


def get_ci_status(repo, head_sha: str) -> tuple[str | None, list[str]]:
    """
    Determine CI status from GitHub check runs and combined commit status.

    Returns (status, failed_names) where status is one of:
      "failed"    — one or more checks conclusively failed
      "canceled"  — one or more checks were cancelled (and none failed)
      "pending"   — checks are still running or queued
      "success"   — all completed checks passed
      None        — no CI configured
    """
    failed_names: list[str] = []
    canceled_names: list[str] = []
    pending = False
    has_checks = False

    # ── Check Runs (newer GitHub Actions / apps) ───────────────────────────────
    try:
        commit = repo.get_commit(head_sha)
        check_runs = list(commit.get_check_runs())
        for cr in check_runs:
            has_checks = True
            if cr.status != "completed":
                pending = True
                continue
            conclusion = cr.conclusion or ""
            if conclusion in _FAILED_CONCLUSIONS:
                failed_names.append(cr.name)
            elif conclusion in _CANCELLED_CONCLUSIONS:
                canceled_names.append(cr.name)
    except GithubException as exc:
        print(f"  WARNING: Could not fetch check runs: {exc}", file=sys.stderr)

    if failed_names:
        return "failed", failed_names
    if canceled_names and not pending:
        return "canceled", canceled_names

    # ── Combined Commit Status (legacy status API) ─────────────────────────────
    try:
        combined = repo.get_commit(head_sha).get_combined_status()
        if combined.state == "failure":
            failed_statuses = [s.context for s in combined.statuses if s.state == "failure"]
            return "failed", failed_statuses
        if combined.state == "error":
            return "failed", [f"combined_status:{combined.state}"]
        if combined.state == "pending":
            pending = True
        elif combined.total_count > 0:
            has_checks = True
    except GithubException as exc:
        print(f"  WARNING: Could not fetch combined commit status: {exc}", file=sys.stderr)

    if not has_checks and not pending:
        return None, []
    if pending:
        return "pending", []
    return "success", []


def print_ci_failures(failed_names: list[str]) -> None:
    """Print failed check names for diagnostics."""
    if failed_names:
        print("  Failed CI checks:", file=sys.stderr)
        for name in failed_names:
            print(f"    - {name}", file=sys.stderr)


def check_only_mode(pr) -> None:
    """Print PR state info to stdout and exit 0."""
    state = "merged" if pr.merged else pr.state  # state is "open" or "closed"
    print(f"state={state}")
    print(f"title={pr.title}")
    sys.exit(0)


def poll_mode(repo, pr, pr_number: int, timeout_minutes: int) -> None:
    """Poll the PR every POLL_INTERVAL_S seconds until terminal state or timeout."""
    deadline = time.time() + timeout_minutes * 60
    iteration = 0

    while time.time() < deadline:
        # Refresh PR state on every iteration (after first immediate check)
        if iteration > 0:
            time.sleep(POLL_INTERVAL_S)
            try:
                pr = repo.get_pull(pr_number)
            except GithubException as exc:
                print(f"[WARN] Could not refresh PR status: {exc}", file=sys.stderr)
                continue

        iteration += 1
        elapsed_min = int((time.time() - (deadline - timeout_minutes * 60)) / 60)

        # ── Terminal states ────────────────────────────────────────────────────
        if pr.merged:
            print(f"[INFO] PR #{pr_number} merged successfully.", file=sys.stderr)
            print("merged")
            sys.exit(0)

        if pr.state == "closed":
            print(f"[ERROR] PR #{pr_number} was closed without merging.", file=sys.stderr)
            print("closed")
            sys.exit(1)

        # ── Check CI status on the head commit ─────────────────────────────────
        head_sha = pr.head.sha
        ci_status, failed_names = get_ci_status(repo, head_sha)

        if ci_status == "failed":
            print(f"[ERROR] CI checks failed on PR #{pr_number} (sha: {head_sha[:8]}).", file=sys.stderr)
            print_ci_failures(failed_names)
            print("pipeline_failed")
            sys.exit(1)

        if ci_status == "canceled":
            print(f"[ERROR] CI checks cancelled on PR #{pr_number} (sha: {head_sha[:8]}).", file=sys.stderr)
            print_ci_failures(failed_names)
            print("pipeline_canceled")
            sys.exit(1)

        # ── Still open — report progress ───────────────────────────────────────
        ci_str = f"ci={ci_status}" if ci_status else "no ci"
        remaining_min = max(0, int((deadline - time.time()) / 60))
        print(
            f"[INFO] PR #{pr_number} still open "
            f"(elapsed={elapsed_min}m, remaining={remaining_min}m, {ci_str}). "
            f"Checking again in {POLL_INTERVAL_S}s...",
            file=sys.stderr,
        )

    # ── Timeout ────────────────────────────────────────────────────────────────
    print(f"[ERROR] Timeout: PR #{pr_number} still open after {timeout_minutes} minutes.", file=sys.stderr)
    print("timeout")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pr-url", required=True, metavar="URL",
        help="Full GitHub PR web URL (e.g. https://github.com/owner/repo/pull/42)",
    )
    parser.add_argument(
        "--timeout", type=int, default=60, metavar="MINUTES",
        help="Polling timeout in minutes (default: 60). Ignored in --check-only mode.",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="Print current PR state and exit immediately without polling.",
    )
    args = parser.parse_args()

    _github_user = require_env("GITHUB_USER", "export GITHUB_USER=yourusername")
    github_token = require_env("GITHUB_TOKEN", "export GITHUB_TOKEN=yourtoken")

    owner, repo_name, pr_number = parse_pr_url(args.pr_url)

    print(f"Connecting to GitHub...", file=sys.stderr)
    g = get_github_client(github_token)

    print(f"Fetching PR #{pr_number} from {owner}/{repo_name}...", file=sys.stderr)
    repo, pr = get_repo_and_pr(g, owner, repo_name, pr_number)

    state = "merged" if pr.merged else pr.state
    print(f"  Title: {pr.title}", file=sys.stderr)
    print(f"  State: {state}", file=sys.stderr)

    if args.check_only:
        check_only_mode(pr)
    else:
        print(f"  Polling every {POLL_INTERVAL_S}s, timeout={args.timeout}m.", file=sys.stderr)
        poll_mode(repo, pr, pr_number, args.timeout)


if __name__ == "__main__":
    main()
