#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "PyGithub>=2.0.0",
# ]
# ///
"""
Fork a GitHub repository to the authenticated user's account.

Idempotent: if a fork already exists for the current user, its URL is returned
without creating a duplicate.

Authentication:
  GITHUB_USER   — required; GitHub username (used to find/create the fork)
  GITHUB_TOKEN  — required; personal access token with `repo` scope

Usage:
  setup_github_fork.py --github-repo-url <url>

Arguments:
  --github-repo-url   Full HTTPS URL of the GitHub repository to fork, e.g.:
                      https://github.com/opendatahub-io/odh-konflux-central

Output (stdout):
  Single line — the full HTTPS URL of the fork (without .git suffix), e.g.:
  https://github.com/jdoe/odh-konflux-central

Exit codes:
  0  Success (fork exists or was created)
  1  Error (auth failure, repo not found, API error)
"""

import argparse
import os
import sys
import time
from urllib.parse import urlparse

from github import Auth, Github, GithubException

FORK_POLL_INTERVAL_S = 5
FORK_POLL_TIMEOUT_S = 60


def require_env(name: str, hint: str) -> str:
    """Return env var value or exit with a helpful message."""
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
    """Create and authenticate a PyGithub client."""
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
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution", "no route")):
            print("ERROR: Cannot reach GitHub. Check your network connection.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to connect to GitHub: {exc}", file=sys.stderr)
        sys.exit(1)


def get_source_repo(g: Github, owner: str, repo_name: str):
    """Fetch the source GitHub repository object."""
    try:
        return g.get_repo(f"{owner}/{repo_name}")
    except GithubException as exc:
        if exc.status == 404:
            print(f"ERROR: Repository not found: {owner}/{repo_name}", file=sys.stderr)
            print("  Check --github-repo-url and GITHUB_TOKEN permissions (needs repo scope).", file=sys.stderr)
        elif exc.status == 403:
            print(f"ERROR: Access denied to repository: {owner}/{repo_name}", file=sys.stderr)
            print("  Check GITHUB_TOKEN permissions (needs repo scope).", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch repository {owner}/{repo_name}: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution")):
            print("ERROR: Cannot reach GitHub. Check your network connection.", file=sys.stderr)
        else:
            print(f"ERROR: Unexpected error fetching repository: {exc}", file=sys.stderr)
        sys.exit(1)


def find_existing_fork(g: Github, source_repo, github_user: str):
    """Return an existing fork owned by github_user that is a fork of source_repo, or None."""
    try:
        candidate = g.get_repo(f"{github_user}/{source_repo.name}")
        if candidate.fork and candidate.parent and candidate.parent.full_name == source_repo.full_name:
            return candidate
        # Repo with same name exists but is not a fork of this source
        return None
    except GithubException as exc:
        if exc.status == 404:
            return None  # No repo with that name in the user's account
        print(f"WARNING: Could not check for existing fork: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"WARNING: Unexpected error checking fork: {exc}", file=sys.stderr)
        return None


def create_fork(g: Github, source_repo, github_user: str):
    """Create a fork and wait for GitHub to finish initialising it."""
    try:
        user = g.get_user()
        fork = user.create_fork(source_repo)
    except GithubException as exc:
        if exc.status == 422:
            # Fork already exists or validation error — caller will search again
            print("WARNING: Fork creation returned 422 (may already exist). Searching again...", file=sys.stderr)
            return None
        print(f"ERROR: Failed to create fork: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  Fork created (id={fork.id}). Waiting for GitHub to finish initialising...", file=sys.stderr)

    deadline = time.time() + FORK_POLL_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(FORK_POLL_INTERVAL_S)
        try:
            refreshed = g.get_repo(fork.full_name)
            _ = refreshed.default_branch  # Accessible means ready
            print(f"  Fork accessible: {refreshed.html_url}", file=sys.stderr)
            return refreshed
        except GithubException as exc:
            print(f"  Fork not yet accessible ({exc}). Retrying...", file=sys.stderr)

    print(
        f"WARNING: Fork did not become accessible within {FORK_POLL_TIMEOUT_S}s. "
        "Proceeding — it may still be initialising in the background.",
        file=sys.stderr,
    )
    return fork


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--github-repo-url",
        required=True,
        metavar="URL",
        help="Full HTTPS URL of the GitHub repository to fork",
    )
    args = parser.parse_args()

    github_user = require_env("GITHUB_USER", "export GITHUB_USER=yourusername")
    github_token = require_env("GITHUB_TOKEN", "export GITHUB_TOKEN=yourtoken")

    src_owner, repo_name = parse_repo_path(args.github_repo_url)

    print(f"Connecting to GitHub...", file=sys.stderr)
    g = get_github_client(github_token)

    print(f"Fetching source repository: {src_owner}/{repo_name}", file=sys.stderr)
    source_repo = get_source_repo(g, src_owner, repo_name)

    print(f"Checking for existing fork owned by {github_user}...", file=sys.stderr)
    fork = find_existing_fork(g, source_repo, github_user)

    if fork:
        fork_url = fork.clone_url.removesuffix(".git")
        print(f"  Fork already exists: {fork_url}", file=sys.stderr)
        print(fork_url)
        return

    print(f"  No existing fork found. Creating fork for '{github_user}'...", file=sys.stderr)
    fork = create_fork(g, source_repo, github_user)

    if fork is None:
        # 422 case — search one more time
        fork = find_existing_fork(g, source_repo, github_user)
        if fork is None:
            print("ERROR: Fork creation returned 422 but no existing fork was found.", file=sys.stderr)
            print("  Try running again, or check your GitHub account manually.", file=sys.stderr)
            sys.exit(1)

    fork_url = fork.clone_url.removesuffix(".git")
    print(f"  Fork ready: {fork_url}", file=sys.stderr)
    print(fork_url)


if __name__ == "__main__":
    main()
