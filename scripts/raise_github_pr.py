#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "PyGithub>=2.0.0",
# ]
# ///
"""
Create a GitHub pull request from a fork branch to a target repository.

Idempotent: if an open PR with the same source branch already exists (from the
same fork), its URL is returned without creating a duplicate.

Authentication:
  GITHUB_USER   — required; GitHub username
  GITHUB_TOKEN  — required; personal access token with `repo` scope

Usage:
  raise_github_pr.py \
    --src-url <url>           # fork URL (mandatory)
    --src-branch <name>       # source branch in fork (mandatory)
    --dest-url <url>          # target repo URL (mandatory)
    [--dest-branch <name>]    # target branch (optional; default: repo's default_branch)
    --title <text>            # PR title (mandatory)
    [--description <text>]    # PR body (optional)

Output (stdout):
  Single line — the web URL of the created or existing PR.

Exit codes:
  0  Success (PR created, or idempotent match returned)
  1  Error (auth failure, repo not found, branch not found, API error)
"""

import argparse
import os
import sys
from urllib.parse import urlparse

from github import Auth, Github, GithubException


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


def get_repo(g: Github, owner: str, repo_name: str, label: str):
    """Fetch a GitHub repository object or exit with a clear error."""
    try:
        return g.get_repo(f"{owner}/{repo_name}")
    except GithubException as exc:
        if exc.status == 404:
            print(f"ERROR: Repository not found ({label}): {owner}/{repo_name}", file=sys.stderr)
            print("  Check the URL and GITHUB_TOKEN permissions (needs repo scope).", file=sys.stderr)
        elif exc.status == 403:
            print(f"ERROR: Access denied to repository ({label}): {owner}/{repo_name}", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch repository {owner}/{repo_name}: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution")):
            print("ERROR: Cannot reach GitHub. Check your network connection.", file=sys.stderr)
        else:
            print(f"ERROR: Unexpected error fetching {owner}/{repo_name}: {exc}", file=sys.stderr)
        sys.exit(1)


def find_existing_pr(dest_repo, head_filter: str, dest_branch: str, *, warn_closed: bool = False):
    """Return an existing open PR whose head matches head_filter and base matches dest_branch.

    head_filter MUST be in "owner:branch" format — the GitHub API silently ignores
    a bare branch name, which causes it to return all open PRs instead of filtering.

    If warn_closed=True, also checks for previously closed (not merged) PRs from the
    same head and logs a warning so the caller is aware.
    """
    try:
        # GitHub API requires "owner:branch" format for the head filter.
        # A bare branch name is silently ignored, returning all open PRs.
        pulls = dest_repo.get_pulls(state="open", head=head_filter, base=dest_branch)
        for pr in pulls:
            # Extra guard: verify the branch actually matches (defence against stale filter).
            if pr.head.label == head_filter or pr.head.ref == head_filter.split(":")[-1]:
                return pr
    except GithubException as exc:
        print(f"WARNING: Could not check for existing open PRs: {exc}", file=sys.stderr)

    if warn_closed:
        try:
            closed = dest_repo.get_pulls(state="closed", head=head_filter, base=dest_branch)
            for pr in closed:
                if not pr.merged:
                    branch = head_filter.split(":")[-1]
                    print(
                        f"WARNING: A previously closed (not merged) PR exists from branch "
                        f"'{branch}': {pr.html_url}  — creating a fresh PR.",
                        file=sys.stderr,
                    )
                    break
        except GithubException:
            pass  # Non-fatal — just skip the warning

    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--src-url", required=True, metavar="URL", help="Fork/source repo URL")
    parser.add_argument("--src-branch", required=True, metavar="BRANCH", help="Source branch in the fork")
    parser.add_argument("--dest-url", required=True, metavar="URL", help="Target repo URL")
    parser.add_argument(
        "--dest-branch", default=None, metavar="BRANCH", help="Target branch (default: repo's default_branch)"
    )
    parser.add_argument("--title", required=True, metavar="TEXT", help="PR title")
    parser.add_argument("--description", default="", metavar="TEXT", help="PR body (optional)")
    args = parser.parse_args()

    _github_user = require_env("GITHUB_USER", "export GITHUB_USER=yourusername")
    github_token = require_env("GITHUB_TOKEN", "export GITHUB_TOKEN=yourtoken")

    src_owner, src_repo_name = parse_repo_path(args.src_url)
    dest_owner, dest_repo_name = parse_repo_path(args.dest_url)

    print("Connecting to GitHub...", file=sys.stderr)
    g = get_github_client(github_token)

    print(f"Fetching source repo (fork):  {src_owner}/{src_repo_name}", file=sys.stderr)
    src_repo = get_repo(g, src_owner, src_repo_name, "source")

    print(f"Fetching target repo (dest):  {dest_owner}/{dest_repo_name}", file=sys.stderr)
    dest_repo = get_repo(g, dest_owner, dest_repo_name, "target")

    dest_branch = args.dest_branch or dest_repo.default_branch
    print(f"Target branch: {dest_branch}", file=sys.stderr)

    # head_filter: GitHub's get_pulls API always requires "owner:branch" format.
    # head_for_create: create_pull uses "owner:branch" for cross-repo, plain branch for same-repo.
    is_cross_repo = src_owner.lower() != dest_owner.lower()
    head_filter = f"{src_owner}:{args.src_branch}"
    head_for_create = head_filter if is_cross_repo else args.src_branch

    # ── Idempotency check ──────────────────────────────────────────────────────
    print(f"Checking for existing open PR (head: {head_filter})...", file=sys.stderr)
    existing = find_existing_pr(dest_repo, head_filter, dest_branch, warn_closed=True)
    if existing:
        print(f"  Open PR already exists: {existing.html_url}", file=sys.stderr)
        print(existing.html_url)
        return

    # ── Verify source branch exists on fork ────────────────────────────────────
    try:
        src_repo.get_branch(args.src_branch)
    except GithubException as exc:
        if exc.status == 404:
            print(f"ERROR: Branch '{args.src_branch}' not found in {src_owner}/{src_repo_name}.", file=sys.stderr)
            print("  Did the push to the source branch succeed?", file=sys.stderr)
        else:
            print(f"ERROR: Failed to verify branch '{args.src_branch}': {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Create PR ──────────────────────────────────────────────────────────────
    print(f"Creating PR: {head_for_create} → {dest_owner}/{dest_repo_name}:{dest_branch}", file=sys.stderr)
    try:
        pr = dest_repo.create_pull(
            title=args.title,
            body=args.description,
            head=head_for_create,
            base=dest_branch,
            maintainer_can_modify=True,
        )
    except GithubException as exc:
        if exc.status == 422:
            # Rare race condition: PR appeared between our check and create
            print("  PR creation returned 422 (conflict). Searching for existing PR...", file=sys.stderr)
            existing = find_existing_pr(dest_repo, head_filter, dest_branch)
            if existing:
                print(f"  Found existing PR: {existing.html_url}", file=sys.stderr)
                print(existing.html_url)
                return
            details = getattr(exc, "data", {}) or {}
            print(f"ERROR: Failed to create pull request: {exc}", file=sys.stderr)
            if details:
                print(f"  Details: {details}", file=sys.stderr)
        else:
            print(f"ERROR: Failed to create pull request: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution")):
            print("ERROR: Cannot reach GitHub. Check your network connection.", file=sys.stderr)
        else:
            print(f"ERROR: Unexpected error creating PR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  PR created: {pr.html_url}", file=sys.stderr)
    print(pr.html_url)


if __name__ == "__main__":
    main()
