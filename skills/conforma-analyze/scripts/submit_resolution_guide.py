#!/usr/bin/env python3
"""Submit a Conforma Violations Resolution Guide to the conforma-reporter repo.

Pushes the generated resolution guide to the same branch and directory as the
source violations CSV via the GitHub Contents API (direct commit).

Usage:
    python3 skills/conforma-analyze/scripts/submit_resolution_guide.py \\
      --guide-file .work/20260610-143449/conforma-violations-resolution-guide.md \\
      --release rhoai-3.5-ea.2 \\
      --target-dir "prod/release_day"

    # Dry run (no commit):
    python3 skills/conforma-analyze/scripts/submit_resolution_guide.py \\
      --guide-file .work/20260610-143449/conforma-violations-resolution-guide.md \\
      --release rhoai-3.5-ea.2 \\
      --target-dir "prod/release_day" \\
      --dry-run
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = "red-hat-data-services/conforma-reporter"
DEFAULT_FILENAME = "conforma-violations-resolution-guide.md"


def _gh_api(endpoint: str, method: str = "GET", input_data: str | None = None) -> tuple[int, str]:
    """Call gh api and return (exit_code, stdout)."""
    cmd = ["gh", "api", endpoint]
    if method != "GET":
        cmd.extend(["-X", method])
    if input_data:
        cmd.extend(["--input", "-"])

    result = subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout


def _get_existing_file_sha(repo: str, path: str, branch: str) -> str | None:
    """Check if file already exists on the branch. Returns SHA if it does."""
    endpoint = f"repos/{repo}/contents/{path}?ref={branch}"
    rc, stdout = _gh_api(endpoint)
    if rc != 0:
        return None
    try:
        data = json.loads(stdout)
        return data.get("sha")
    except (json.JSONDecodeError, KeyError):
        return None


def _check_branch_exists(repo: str, branch: str) -> bool:
    """Verify the branch exists."""
    endpoint = f"repos/{repo}/branches/{branch}"
    rc, _ = _gh_api(endpoint)
    return rc == 0


def submit_resolution_guide(
    guide_file: str,
    release: str,
    target_dir: str,
    repo: str = DEFAULT_REPO,
    message: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Submit the resolution guide to GitHub.

    Returns a dict with: url, sha, committed, dry_run
    """
    guide_path = Path(guide_file)
    if not guide_path.exists():
        return {"error": f"Guide file not found: {guide_file}", "committed": False}

    target_path = f"{target_dir.rstrip('/')}/{DEFAULT_FILENAME}"
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

    endpoint = f"repos/{repo}/contents/{target_path}"
    rc, stdout = _gh_api(endpoint, method="PUT", input_data=json.dumps(payload))

    if rc != 0:
        error_detail = ""
        try:
            err_data = json.loads(stdout)
            error_detail = err_data.get("message", stdout[:200])
        except json.JSONDecodeError:
            error_detail = stdout[:200] if stdout else "Unknown error"

        if "protected branch" in error_detail.lower() or rc == 1:
            return {
                "error": f"Cannot commit to {release}: {error_detail}. "
                "Branch may be protected — consider using PR mode.",
                "committed": False,
            }
        return {"error": f"GitHub API error: {error_detail}", "committed": False}

    try:
        result = json.loads(stdout)
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
        required=True,
        help="Directory in repo to place the file (e.g. prod/release_day)",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repo (default: {DEFAULT_REPO})")
    parser.add_argument("--message", default=None, help="Commit message")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without committing")
    args = parser.parse_args()

    result = submit_resolution_guide(
        guide_file=args.guide_file,
        release=args.release,
        target_dir=args.target_dir,
        repo=args.repo,
        message=args.message,
        dry_run=args.dry_run,
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
