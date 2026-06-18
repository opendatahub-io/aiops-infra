#!/usr/bin/env python3
"""Submit a Conforma Violations Resolution Guide to the conforma-reporter repo.

Pushes the generated resolution guide to the same branch and directory as the
source violations CSV via the GitHub Contents API (direct commit).

Usage:
    # Derive target directory from fetch metadata (preferred):
    python3 skills/conforma-analyze/scripts/submit_resolution_guide.py \\
      --guide-file .work/20260610-143449/conforma-violations-resolution-guide.md \\
      --release rhoai-3.5-ea.2 \\
      --metadata-file .work/20260610-143449/fetch-metadata.json

    # Explicit target directory:
    python3 skills/conforma-analyze/scripts/submit_resolution_guide.py \\
      --guide-file .work/20260610-143449/conforma-violations-resolution-guide.md \\
      --release rhoai-3.5-ea.2 \\
      --target-dir "prod/release_day"

    # Dry run (no commit):
    python3 skills/conforma-analyze/scripts/submit_resolution_guide.py \\
      --guide-file .work/20260610-143449/conforma-violations-resolution-guide.md \\
      --release rhoai-3.5-ea.2 \\
      --metadata-file .work/20260610-143449/fetch-metadata.json \\
      --dry-run
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

import _setup_env  # noqa: F401 -- loads .work/.env and adds scripts/ to sys.path

DEFAULT_REPO = "red-hat-data-services/conforma-reporter"
DEFAULT_FILENAME = "conforma-violations-resolution-guide.md"
GITHUB_API = "https://api.github.com"


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


def _resolve_target_dir(metadata_file: str | None, release: str, target_dir: str | None) -> str | None:
    """Derive target directory from metadata or explicit flag.

    Returns the resolved target_dir string, or None on error.
    """
    if target_dir:
        return target_dir

    if not metadata_file:
        return None

    meta_path = Path(metadata_file)
    if not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        source_path = meta["releases"][release]["source_path"]
        return str(Path(source_path).parent)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def submit_resolution_guide(
    guide_file: str,
    release: str,
    target_dir: str | None = None,
    repo: str = DEFAULT_REPO,
    message: str | None = None,
    dry_run: bool = False,
    metadata_file: str | None = None,
) -> dict:
    """Submit the resolution guide to GitHub.

    Returns a dict with: url, sha, committed, dry_run
    """
    guide_path = Path(guide_file)
    if not guide_path.exists():
        return {"error": f"Guide file not found: {guide_file}", "committed": False}

    resolved_dir = _resolve_target_dir(metadata_file, release, target_dir)
    if not resolved_dir:
        return {
            "error": "Could not determine target directory. "
            "Provide --target-dir or --metadata-file with a valid release entry.",
            "committed": False,
        }

    target_path = f"{resolved_dir.rstrip('/')}/{DEFAULT_FILENAME}"
    commit_message = message or f"Update conforma violations resolution guide for {release}"

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

    return {
        "url": file_url,
        "sha": file_sha,
        "target_path": target_path,
        "branch": release,
        "repo": repo,
        "committed": True,
        "overwritten": existing_sha is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit a Conforma Violations Resolution Guide to GitHub")
    parser.add_argument("--guide-file", required=True, help="Path to the generated resolution guide markdown")
    parser.add_argument("--release", required=True, help="Branch name (e.g. rhoai-3.5-ea.2)")
    parser.add_argument(
        "--target-dir",
        default=None,
        help="Directory in repo to place the file (e.g. prod/release_day). "
        "Optional when --metadata-file is provided.",
    )
    parser.add_argument(
        "--metadata-file",
        default=None,
        help="Path to fetch-metadata.json — auto-derives target directory from source_path",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repo (default: {DEFAULT_REPO})")
    parser.add_argument("--message", default=None, help="Commit message")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without committing")
    args = parser.parse_args()

    if not args.target_dir and not args.metadata_file:
        parser.error("either --target-dir or --metadata-file is required")

    result = submit_resolution_guide(
        guide_file=args.guide_file,
        release=args.release,
        target_dir=args.target_dir,
        repo=args.repo,
        message=args.message,
        dry_run=args.dry_run,
        metadata_file=args.metadata_file,
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
