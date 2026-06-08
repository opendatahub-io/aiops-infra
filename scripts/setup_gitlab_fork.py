#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "python-gitlab>=3.0.0",
# ]
# ///
"""
Fork a GitLab project to the authenticated user's personal namespace.

Idempotent: if a fork already exists for the current user, its URL is returned
without creating a duplicate.

Authentication:
  GITLAB_USER   — required; GitLab username (used to find/create the fork)
  GITLAB_TOKEN  — required; personal access token with api + write_repository scopes

Usage:
  setup_gitlab_fork.py --gitlab-repo-url <url>

Arguments:
  --gitlab-repo-url   Full HTTPS URL of the GitLab project to fork, e.g.:
                      https://gitlab.cee.redhat.com/service/app-interface

Output (stdout):
  Single line — the full HTTPS URL of the fork, e.g.:
  https://gitlab.cee.redhat.com/jdoe/app-interface

Exit codes:
  0  Success (fork exists or was created)
  1  Error (auth failure, project not found, API error, VPN issue)
"""

import argparse
import os
import sys
import time
import warnings
from urllib.parse import urlparse

import gitlab
from gitlab.exceptions import GitlabAuthenticationError, GitlabError, GitlabGetError

FORK_POLL_INTERVAL_S = 3
FORK_POLL_TIMEOUT_S = 30


def require_env(name: str, hint: str) -> str:
    """Return env var value or exit with a helpful message."""
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: {name} environment variable is not set.", file=sys.stderr)
        print(f"  {hint}", file=sys.stderr)
        sys.exit(1)
    return value


def parse_gitlab_base_url(repo_url: str) -> str:
    """Extract scheme + host from a GitLab URL (e.g. https://gitlab.cee.redhat.com)."""
    parsed = urlparse(repo_url)
    if not parsed.scheme or not parsed.netloc:
        print(f"ERROR: Cannot parse GitLab URL: {repo_url}", file=sys.stderr)
        print("  Expected format: https://<host>/<namespace>/<project>", file=sys.stderr)
        sys.exit(1)
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_project_path(repo_url: str) -> str:
    """Extract the project path from a GitLab URL (e.g. 'service/app-interface')."""
    parsed = urlparse(repo_url)
    path = parsed.path.strip("/").removesuffix(".git")
    if not path or "/" not in path:
        print(f"ERROR: Cannot extract project path from URL: {repo_url}", file=sys.stderr)
        print("  Expected format: https://<host>/<namespace>/<project>", file=sys.stderr)
        sys.exit(1)
    return path


def _ssl_verify() -> bool:
    """Return False if GITLAB_SSL_VERIFY is explicitly set to a falsy value."""
    val = os.environ.get("GITLAB_SSL_VERIFY", "true").strip().lower()
    skip = val in ("0", "false", "no", "off")
    if skip:
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    return not skip


def get_gitlab_client(base_url: str, token: str) -> gitlab.Gitlab:
    """Create and authenticate a python-gitlab client."""
    verify = _ssl_verify()
    try:
        gl = gitlab.Gitlab(url=base_url, private_token=token, ssl_verify=verify)
        gl.auth()
        return gl
    except GitlabAuthenticationError:
        print("ERROR: GitLab authentication failed. Check GITLAB_TOKEN.", file=sys.stderr)
        print(f"  GitLab instance: {base_url}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if "ssl" in msg or "certificate" in msg:
            print(f"ERROR: SSL certificate verification failed for {base_url}.", file=sys.stderr)
            print("  Set GITLAB_SSL_VERIFY=false to skip verification for internal CAs.", file=sys.stderr)
            sys.exit(1)
        if any(k in msg for k in ("connection", "timeout", "name resolution", "no route")):
            print(f"ERROR: Cannot reach {base_url}. Ensure VPN is active.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to connect to GitLab: {exc}", file=sys.stderr)
        sys.exit(1)


def get_source_project(gl: gitlab.Gitlab, project_path: str, base_url: str):
    """Fetch the source GitLab project object."""
    try:
        return gl.projects.get(project_path)
    except GitlabGetError as exc:
        if exc.response_code == 404:
            print(f"ERROR: Project not found: {project_path}", file=sys.stderr)
            print(f"  Check APP_INTERFACE_REPO_URL and VPN connectivity to {base_url}", file=sys.stderr)
        elif exc.response_code == 403:
            print(f"ERROR: Access denied to project: {project_path}", file=sys.stderr)
            print("  Check GITLAB_TOKEN permissions (needs api scope).", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch project {project_path}: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution")):
            print(f"ERROR: Cannot reach {base_url}. Ensure VPN is active.", file=sys.stderr)
        else:
            print(f"ERROR: Unexpected error fetching project: {exc}", file=sys.stderr)
        sys.exit(1)


def find_existing_fork(project, gitlab_user: str):
    """Return an existing fork owned by gitlab_user, or None."""
    try:
        forks = project.forks.list(all=True)
        for fork in forks:
            ns = fork.namespace if isinstance(fork.namespace, dict) else {}
            if ns.get("path", "").lower() == gitlab_user.lower():
                return fork
    except GitlabError as exc:
        print(f"WARNING: Could not list forks (will attempt to create): {exc}", file=sys.stderr)
    return None


def _get_forked_from_id(project) -> int | None:
    """Extract the forked_from_project id from a project object."""
    forked_from = getattr(project, "forked_from_project", None)
    if forked_from is None:
        return None
    if isinstance(forked_from, dict):
        return forked_from.get("id")
    return getattr(forked_from, "id", None)


def find_same_name_project(gl: gitlab.Gitlab, gitlab_user: str, project_name: str):
    """Look up <gitlab_user>/<project_name> directly, return project or None."""
    candidate_path = f"{gitlab_user}/{project_name}"
    try:
        return gl.projects.get(candidate_path)
    except GitlabGetError:
        return None
    except Exception:
        return None


def create_fork(project, gitlab_user: str):
    """Create a fork and wait for it to finish importing."""
    try:
        fork = project.forks.create({"namespace": gitlab_user})
    except GitlabError as exc:
        if getattr(exc, "response_code", None) == 409:
            print("WARNING: Fork creation returned 409 (may already exist). Searching again...", file=sys.stderr)
            return None
        print(f"ERROR: Failed to create fork: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  Fork created (id={fork.id}). Waiting for import to finish...", file=sys.stderr)

    deadline = time.time() + FORK_POLL_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(FORK_POLL_INTERVAL_S)
        try:
            refreshed = fork.manager.gitlab.projects.get(fork.id)
            status = getattr(refreshed, "import_status", "finished")
            print(f"  Import status: {status}", file=sys.stderr)
            if status in ("finished", "none", None):
                return refreshed
        except GitlabError as exc:
            print(f"  WARNING: Could not refresh fork status: {exc}", file=sys.stderr)

    print(
        f"WARNING: Fork import did not finish within {FORK_POLL_TIMEOUT_S}s. "
        "Proceeding — it may still complete in the background.",
        file=sys.stderr,
    )
    return fork


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--gitlab-repo-url",
        required=True,
        metavar="URL",
        help="Full HTTPS URL of the GitLab project to fork",
    )
    args = parser.parse_args()

    gitlab_user = require_env("GITLAB_USER", "export GITLAB_USER=yourusername")
    gitlab_token = require_env("GITLAB_TOKEN", "export GITLAB_TOKEN=yourtoken")

    base_url = parse_gitlab_base_url(args.gitlab_repo_url)
    project_path = parse_project_path(args.gitlab_repo_url)
    project_name = project_path.rsplit("/", 1)[-1]

    print(f"Connecting to {base_url}...", file=sys.stderr)
    gl = get_gitlab_client(base_url, gitlab_token)

    print(f"Fetching source project: {project_path}", file=sys.stderr)
    source = get_source_project(gl, project_path, base_url)

    print(f"Checking for existing fork owned by {gitlab_user}...", file=sys.stderr)
    fork = find_existing_fork(source, gitlab_user)

    if fork:
        print(f"  Fork already exists: {fork.http_url_to_repo}", file=sys.stderr)
        print(fork.http_url_to_repo)
        return

    # No fork found via the forks API. Before creating, check if the user
    # already has a same-named project that could be reused or is blocking.
    candidate = find_same_name_project(gl, gitlab_user, project_name)
    if candidate is not None:
        parent_id = _get_forked_from_id(candidate)
        if parent_id == source.id:
            # Fork exists with correct parent but wasn't listed (API lag)
            print(f"  Fork found by name with correct parent: {candidate.http_url_to_repo}", file=sys.stderr)
            print(candidate.http_url_to_repo)
            return
        if parent_id is not None:
            forked_from = getattr(candidate, "forked_from_project", {})
            stale_parent = (
                forked_from.get("path_with_namespace", parent_id) if isinstance(forked_from, dict) else parent_id
            )
            print(
                f"ERROR: {gitlab_user}/{project_name} is forked from '{stale_parent}', not '{project_path}'.",
                file=sys.stderr,
            )
        else:
            print(f"ERROR: {gitlab_user}/{project_name} already exists but is not a fork.", file=sys.stderr)
        print(f"  Manually delete or rename it on {base_url} and retry.", file=sys.stderr)
        sys.exit(1)

    print(f"  Creating fork in namespace '{gitlab_user}'...", file=sys.stderr)
    fork = create_fork(source, gitlab_user)

    if fork is None:
        # 409 case — search one more time
        fork = find_existing_fork(source, gitlab_user)
        if fork is None:
            candidate = find_same_name_project(gl, gitlab_user, project_name)
            if candidate is not None and _get_forked_from_id(candidate) == source.id:
                fork = candidate
        if fork is None:
            print("ERROR: Fork creation returned 409 but no matching fork was found.", file=sys.stderr)
            print(f"  A project named '{project_name}' may already exist under {gitlab_user}/.", file=sys.stderr)
            print(f"  Check {base_url}/{gitlab_user}/{project_name} and retry.", file=sys.stderr)
            sys.exit(1)

    print(f"  Fork ready: {fork.http_url_to_repo}", file=sys.stderr)
    print(fork.http_url_to_repo)


if __name__ == "__main__":
    main()
