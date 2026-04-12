#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "python-gitlab>=3.0.0",
# ]
# ///
"""
Create a cross-project GitLab merge request from a fork branch to the target project's master.

Idempotent: if an open MR with the same source branch already exists (from the same fork),
its URL is returned without creating a duplicate.

Authentication:
  GITLAB_USER   — required; GitLab username
  GITLAB_TOKEN  — required; personal access token with api + write_repository scopes

Usage:
  raise_gitlab_mr.py \
    --src-url <url>           # fork URL (mandatory)
    --src-branch <name>       # source branch in fork (mandatory)
    --dest-url <url>          # target project URL, e.g. app-interface (mandatory)
    [--dest-branch <name>]    # target branch (optional; default: target project's default_branch)
    --title <text>            # MR title (mandatory)
    [--description <text>]    # MR description (optional)

Output (stdout):
  Single line — the web URL of the created or existing MR.

Exit codes:
  0  Success (MR created, or idempotent match returned)
  1  Error (auth failure, project not found, API error, VPN issue)
"""

import argparse
import os
import sys
from urllib.parse import urlparse

import gitlab
from gitlab.exceptions import GitlabAuthenticationError, GitlabError, GitlabGetError


def require_env(name: str, hint: str) -> str:
    """Return env var value or exit with a helpful message."""
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: {name} environment variable is not set.", file=sys.stderr)
        print(f"  {hint}", file=sys.stderr)
        sys.exit(1)
    return value


def parse_gitlab_base_url(url: str) -> str:
    """Extract scheme + host from a GitLab URL."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        print(f"ERROR: Cannot parse GitLab URL: {url}", file=sys.stderr)
        sys.exit(1)
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_project_path(url: str) -> str:
    """Extract the project path from a GitLab URL (strips .git suffix)."""
    parsed = urlparse(url)
    return parsed.path.strip("/").removesuffix(".git")


def get_gitlab_client(base_url: str, token: str) -> gitlab.Gitlab:
    """Create and authenticate a python-gitlab client."""
    try:
        gl = gitlab.Gitlab(url=base_url, private_token=token)
        gl.auth()
        return gl
    except GitlabAuthenticationError:
        print("ERROR: GitLab authentication failed. Check GITLAB_TOKEN.", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution", "no route")):
            print(f"ERROR: Cannot reach {base_url}. Ensure VPN is active.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to connect to GitLab: {exc}", file=sys.stderr)
        sys.exit(1)


def get_project(gl: gitlab.Gitlab, project_path: str, label: str):
    """Fetch a GitLab project or exit with a clear error."""
    try:
        return gl.projects.get(project_path)
    except GitlabGetError as exc:
        if exc.response_code == 404:
            print(f"ERROR: Project not found ({label}): {project_path}", file=sys.stderr)
            print("  Check VPN connectivity and that the URL is correct.", file=sys.stderr)
        elif exc.response_code == 403:
            print(f"ERROR: Access denied to project ({label}): {project_path}", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch project {project_path}: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution")):
            host = gl.url
            print(f"ERROR: Cannot reach {host}. Ensure VPN is active.", file=sys.stderr)
        else:
            print(f"ERROR: Unexpected error fetching {project_path}: {exc}", file=sys.stderr)
        sys.exit(1)


def find_existing_mr(target_project, source_project_id: int, src_branch: str):
    """Return an existing open MR from the fork branch, or None."""
    try:
        mrs = target_project.mergerequests.list(
            state="opened",
            source_branch=src_branch,
            all=True,
        )
        for mr in mrs:
            # Cross-project MRs have source_project_id set to the fork's ID
            if getattr(mr, "source_project_id", None) == source_project_id:
                return mr
    except GitlabError as exc:
        print(f"WARNING: Could not check for existing MRs: {exc}", file=sys.stderr)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--src-url",     required=True, metavar="URL",    help="Fork URL (source project)")
    parser.add_argument("--src-branch",  required=True, metavar="BRANCH", help="Source branch in the fork")
    parser.add_argument("--dest-url",    required=True, metavar="URL",    help="Target project URL (e.g. app-interface)")
    parser.add_argument("--dest-branch", default=None,  metavar="BRANCH", help="Target branch (default: project's default_branch)")
    parser.add_argument("--title",       required=True, metavar="TEXT",   help="MR title")
    parser.add_argument("--description", default="",    metavar="TEXT",   help="MR description (optional)")
    args = parser.parse_args()

    _gitlab_user = require_env("GITLAB_USER", "export GITLAB_USER=yourusername")
    gitlab_token = require_env("GITLAB_TOKEN", "export GITLAB_TOKEN=yourtoken")

    # Both URLs must live on the same GitLab instance
    src_base  = parse_gitlab_base_url(args.src_url)
    dest_base = parse_gitlab_base_url(args.dest_url)
    if src_base != dest_base:
        print(f"ERROR: --src-url and --dest-url must be on the same GitLab instance.", file=sys.stderr)
        print(f"  src:  {src_base}", file=sys.stderr)
        print(f"  dest: {dest_base}", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to {dest_base}...", file=sys.stderr)
    gl = get_gitlab_client(dest_base, gitlab_token)

    src_path  = parse_project_path(args.src_url)
    dest_path = parse_project_path(args.dest_url)

    print(f"Fetching source project (fork):   {src_path}", file=sys.stderr)
    fork_project = get_project(gl, src_path, "fork")

    print(f"Fetching target project (dest):   {dest_path}", file=sys.stderr)
    target_project = get_project(gl, dest_path, "target")

    dest_branch = args.dest_branch or target_project.default_branch
    print(f"Target branch: {dest_branch}", file=sys.stderr)

    # ── Idempotency check ──────────────────────────────────────────────────────
    print(f"Checking for existing open MR (branch: {args.src_branch})...", file=sys.stderr)
    existing = find_existing_mr(target_project, fork_project.id, args.src_branch)
    if existing:
        print(f"  Open MR already exists: {existing.web_url}", file=sys.stderr)
        print(existing.web_url)
        return

    # ── Verify source branch exists on fork ────────────────────────────────────
    try:
        fork_project.branches.get(args.src_branch)
    except GitlabGetError:
        print(f"ERROR: Branch '{args.src_branch}' not found on fork project '{src_path}'.", file=sys.stderr)
        print("  Did the push in setup_gitlab_playpen.sh succeed?", file=sys.stderr)
        sys.exit(1)

    # ── Create MR ──────────────────────────────────────────────────────────────
    print(f"Creating cross-project MR: {src_path}:{args.src_branch} → {dest_path}:{dest_branch}", file=sys.stderr)
    try:
        mr = target_project.mergerequests.create({
            "source_project_id": fork_project.id,
            "source_branch":     args.src_branch,
            "target_branch":     dest_branch,
            "title":             args.title,
            "description":       args.description,
            "remove_source_branch": False,
        })
    except GitlabError as exc:
        response_code = getattr(exc, "response_code", None)
        if response_code == 409:
            # Rare race condition: MR appeared between our check and create
            print("  MR creation returned 409 (conflict). Searching for existing MR...", file=sys.stderr)
            existing = find_existing_mr(target_project, fork_project.id, args.src_branch)
            if existing:
                print(f"  Found existing MR: {existing.web_url}", file=sys.stderr)
                print(existing.web_url)
                return
        print(f"ERROR: Failed to create merge request: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution")):
            print(f"ERROR: Cannot reach {dest_base}. Ensure VPN is active.", file=sys.stderr)
        else:
            print(f"ERROR: Unexpected error creating MR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  MR created: {mr.web_url}", file=sys.stderr)
    print(mr.web_url)


if __name__ == "__main__":
    main()
