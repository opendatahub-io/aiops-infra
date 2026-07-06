#!/usr/bin/env python3
"""submit_resolution_guide — Submit a Conforma Resolution Guide to the conforma-reporter repo.

PUBLIC API:
    submit_resolution_guide(guide_file, release, environment, repo, message, dry_run, metadata_file) -> dict  [line 128]
    main() -> int  [line 249]

INTERNAL SECTIONS:
    Main: _get_github_token, _gh_headers, _get_existing_file_sha, _check_branch_exists, _resolve_old_path, ... (+1 more)

DEPENDENCIES: argparse, base64, conforma_constants, conforma_context_ops, json, os, pathlib, requests, subprocess, sys

"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

import _setup_env  # noqa: F401 -- loads ~/.conforma/.env and adds scripts/ to sys.path

import conforma_context_ops  # noqa: E402
from conforma_constants import CONFORMA_REPORTER_REPO, GITHUB_API  # noqa: E402

DEFAULT_FILENAME = "conforma-status-and-resolution-guide.md"


def _get_github_token() -> str:
    """Get GitHub token from env vars or gh CLI."""
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def _gh_headers() -> dict[str, str]:
    token = _get_github_token()
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_existing_file_sha(repo: str, path: str, branch: str) -> str | None:
    """Check if file already exists on the branch. Returns SHA if it does."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}?ref={branch}"
    try:
        resp = requests.get(url, headers=_gh_headers(), timeout=30)
        if resp.status_code != 200:
            return None
        return resp.json().get("sha")
    except (requests.RequestException, json.JSONDecodeError, KeyError):
        return None


def _check_branch_exists(repo: str, branch: str) -> bool:
    """Verify the branch exists."""
    url = f"{GITHUB_API}/repos/{repo}/branches/{branch}"
    try:
        resp = requests.get(url, headers=_gh_headers(), timeout=15)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def _resolve_old_path(metadata_file: str | None, release: str) -> str | None:
    """Derive the legacy target path from metadata for cleanup.

    Returns the old path (e.g. prod/future/build_type_latest/conforma-violations-resolution-guide.md)
    or None if metadata is unavailable.
    """
    if not metadata_file:
        return None

    meta_path = Path(metadata_file)
    if not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        source_path = meta["releases"][release]["source_path"]
        old_dir = str(Path(source_path).parent)
        return f"{old_dir.rstrip('/')}/conforma-violations-resolution-guide.md"
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _delete_file_if_exists(repo: str, path: str, branch: str, message: str) -> dict | None:
    """Delete a file from the repo if it exists. Returns result dict or None."""
    sha = _get_existing_file_sha(repo, path, branch)
    if not sha:
        return None
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    payload = {"message": message, "sha": sha, "branch": branch}
    try:
        resp = requests.delete(url, headers=_gh_headers(), json=payload, timeout=60)
        if resp.status_code == 200:
            return {"deleted": path, "branch": branch}
    except requests.RequestException:
        pass
    return None


def submit_resolution_guide(
    guide_file: str,
    release: str,
    environment: str,
    repo: str = CONFORMA_REPORTER_REPO,
    message: str | None = None,
    dry_run: bool = False,
    metadata_file: str | None = None,
) -> dict:
    """Submit the resolution guide to the environment-specific directory on GitHub.

    The guide is placed at ``{environment}/conforma-status-and-resolution-guide.md``
    (e.g. ``stage/conforma-status-and-resolution-guide.md``).

    Returns a dict with: url, sha, committed, dry_run
    """
    guide_path = Path(guide_file)
    if not guide_path.exists():
        return {"error": f"Guide file not found: {guide_file}", "committed": False}

    target_path = f"{environment}/{DEFAULT_FILENAME}"
    commit_message = message or f"Update conforma resolution guide for {release}"

    if dry_run:
        url = f"https://github.com/{repo}/blob/{release}/{target_path}"
        return {
            "url": url,
            "target_path": target_path,
            "branch": release,
            "repo": repo,
            "message": commit_message,
            "committed": False,
            "dry_run": True,
            "question_text": f"Submit {target_path} to GitHub ({repo}, branch {release})?",
            "question_options": ["Yes, submit", "No, skip"],
        }

    if not _check_branch_exists(repo, release):
        return {
            "error": f"Branch '{release}' not found in {repo}",
            "committed": False,
        }

    existing_sha = _get_existing_file_sha(repo, target_path, release)

    content_bytes = guide_path.read_bytes()
    content_b64 = base64.b64encode(content_bytes).decode("ascii")

    payload: dict = {
        "message": commit_message,
        "content": content_b64,
        "branch": release,
    }
    if existing_sha:
        payload["sha"] = existing_sha

    url = f"{GITHUB_API}/repos/{repo}/contents/{target_path}"
    try:
        resp = requests.put(url, headers=_gh_headers(), json=payload, timeout=60)
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}", "committed": False}

    if resp.status_code not in (200, 201):
        error_detail = ""
        try:
            err_data = resp.json()
            error_detail = err_data.get("message", resp.text[:200])
        except (json.JSONDecodeError, ValueError):
            error_detail = resp.text[:200] if resp.text else "Unknown error"

        if "protected branch" in error_detail.lower():
            return {
                "error": f"Cannot commit to {release}: {error_detail}. "
                "Branch may be protected — consider using PR mode.",
                "committed": False,
            }
        return {"error": f"GitHub API error {resp.status_code}: {error_detail}", "committed": False}

    try:
        result = resp.json()
        file_url = result.get("content", {}).get("html_url", "")
        file_sha = result.get("content", {}).get("sha", "")
    except (json.JSONDecodeError, KeyError):
        file_url = f"https://github.com/{repo}/blob/{release}/{target_path}"
        file_sha = ""

    result_dict: dict = {
        "url": file_url,
        "sha": file_sha,
        "target_path": target_path,
        "branch": release,
        "repo": repo,
        "committed": True,
        "overwritten": existing_sha is not None,
    }

    cleaned = []
    old_path = _resolve_old_path(metadata_file, release)
    if old_path and not dry_run:
        cleanup = _delete_file_if_exists(
            repo, old_path, release,
            f"Remove legacy resolution guide from {old_path}",
        )
        if cleanup:
            cleaned.append(cleanup["deleted"])

    root_legacy = DEFAULT_FILENAME
    if root_legacy != target_path and not dry_run:
        cleanup = _delete_file_if_exists(
            repo, root_legacy, release,
            f"Remove legacy resolution guide from repo root",
        )
        if cleanup:
            cleaned.append(cleanup["deleted"])

    if cleaned:
        result_dict["cleaned_up"] = cleaned

    return result_dict


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit a Conforma Resolution Guide to GitHub")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Conforma run directory (auto-discovered from ~/.conforma/.conforma-active if omitted)",
    )
    parser.add_argument("--guide-file", default=None, help="Path to the generated resolution guide markdown")
    parser.add_argument("--release", default=None, help="Branch name (e.g. rhoai-3.5-ea.2)")
    parser.add_argument("--environment", default=None, choices=["prod", "stage"],
                        help="Target environment — determines the directory in the repo")
    parser.add_argument(
        "--metadata-file",
        default=None,
        help="Path to fetch-metadata.json — used to clean up legacy guide from old location",
    )
    parser.add_argument("--repo", default=CONFORMA_REPORTER_REPO, help=f"GitHub repo (default: {CONFORMA_REPORTER_REPO})")
    parser.add_argument("--message", default=None, help="Commit message")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without committing")
    args = parser.parse_args()

    context = None
    run_dir = None
    try:
        run_dir = conforma_context_ops.discover_run_dir(args.run_dir)
        context = conforma_context_ops.load(run_dir)
    except FileNotFoundError:
        if args.run_dir:
            raise

    environment = conforma_context_ops.resolve_arg(args, "environment", context, "environment")
    release = conforma_context_ops.resolve_arg(args, "release", context, "application.release")

    guide_file = args.guide_file
    if guide_file is None and context:
        ctx_guide = conforma_context_ops.get(run_dir, "steps.resolution_guide.guide_file", None)
        if ctx_guide:
            guide_file = str(Path(run_dir) / ctx_guide)
    if guide_file is None:
        print("Error: --guide-file is required when no run context is available", file=sys.stderr)
        return 1

    metadata_file = args.metadata_file

    result = submit_resolution_guide(
        guide_file=guide_file,
        release=release,
        environment=environment,
        repo=args.repo,
        message=args.message,
        dry_run=args.dry_run,
        metadata_file=metadata_file,
    )

    print(json.dumps(result, indent=2))

    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1

    if result.get("dry_run"):
        print(f"DRY RUN: Would commit to {result['url']}", file=sys.stderr)
    else:
        action = "Updated" if result.get("overwritten") else "Created"
        print(f"{action}: {result['url']}", file=sys.stderr)

    if run_dir and not args.dry_run:
        conforma_context_ops.update_step(run_dir, "submit", "completed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
