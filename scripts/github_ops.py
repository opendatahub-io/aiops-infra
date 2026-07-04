"""github_ops.py -- GitHub primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess

import requests

GITHUB_API = "https://api.github.com"


def _run_gh(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    gh_path = shutil.which("gh")
    if not gh_path:
        raise FileNotFoundError("'gh' CLI not found on PATH")
    return subprocess.run(
        [gh_path, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        close_fds=True,
    )


def get_token() -> str:
    """Get GitHub token from env vars or gh CLI.

    Resolution order:
      1. GITHUB_TOKEN env var
      2. GH_TOKEN env var
      3. `gh auth token` CLI (if gh is installed)
    """
    import os

    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    try:
        result = _run_gh(["auth", "token"], timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def verify_auth() -> dict:
    """Check GitHub authentication via API.

    Uses get_token() which checks GITHUB_TOKEN / GH_TOKEN env vars,
    falling back to `gh auth token` if the CLI happens to be installed.
    """
    token = get_token()
    if not token:
        return {
            "ok": False,
            "user": None,
            "error": "No GitHub token found. Set GITHUB_TOKEN in ~/.conforma/.env.",
        }
    try:
        resp = requests.get(
            f"{GITHUB_API}/user",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        if resp.status_code == 401:
            return {"ok": False, "user": None, "error": "Token is invalid or expired (HTTP 401)"}
        if resp.status_code != 200:
            return {"ok": False, "user": None, "error": f"GitHub API error {resp.status_code}"}
        user = resp.json().get("login")
        return {"ok": True, "user": user, "error": None}
    except requests.RequestException as exc:
        return {"ok": False, "user": None, "error": f"GitHub API request failed: {exc}"}


def create_pr(
    repo: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main",
) -> dict:
    """Create a pull request via GitHub API.

    Returns {"pr_url": str, "pr_number": int} or {"error": str}.
    """
    token = get_token()
    if not token:
        return {"error": "No GitHub token found (set GITHUB_TOKEN in ~/.conforma/.env)"}

    try:
        resp = requests.post(
            f"{GITHUB_API}/repos/{repo}/pulls",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": title,
                "body": body,
                "head": head_branch,
                "base": base_branch,
            },
            timeout=60,
        )
        if resp.status_code == 422:
            return {"error": f"PR creation failed (422): {resp.text[:300]}"}
        if resp.status_code not in (201, 200):
            return {"error": f"GitHub API error {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        pr_url = data.get("html_url", "")
        pr_number = data.get("number")

        if not pr_url or pr_number is None:
            return {"error": "PR created but could not determine PR URL/number"}

        return {"pr_url": pr_url, "pr_number": pr_number}
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}"}


def get_file(repo: str, path: str, ref: str = "main") -> dict:
    """Get file content via GitHub API."""
    token = get_token()
    if not token:
        return {"error": "No GitHub token found (set GITHUB_TOKEN in ~/.conforma/.env)"}

    url = f"{GITHUB_API}/repos/{repo}/contents/{path.lstrip('/')}"
    try:
        response = requests.get(
            url,
            params={"ref": ref},
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        if response.status_code == 404:
            return {"error": f"File not found: {repo}/{path}@{ref}"}
        if response.status_code != 200:
            return {"error": f"GitHub API error {response.status_code}: {response.text[:300]}"}

        data = response.json()
        encoding = data.get("encoding")
        raw_content = data.get("content", "")
        if encoding == "base64":
            content = base64.b64decode(raw_content).decode("utf-8")
        else:
            content = raw_content

        sha = data.get("sha", "")
        if not sha:
            return {"error": "GitHub API response missing file sha"}

        return {"content": content, "sha": sha}
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}"}
    except (UnicodeDecodeError, ValueError) as exc:
        return {"error": f"Failed to decode file content: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def get_repo(repo: str) -> dict:
    """Get repository metadata via GitHub API."""
    token = get_token()
    if not token:
        return {"error": "No GitHub token found (set GITHUB_TOKEN in ~/.conforma/.env)"}

    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        if resp.status_code == 404:
            return {"error": f"Repository not found: {repo}"}
        if resp.status_code != 200:
            return {"error": f"GitHub API error {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        return {
            "full_name": data["full_name"],
            "default_branch": data["default_branch"],
            "private": bool(data.get("private", False)),
        }
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}"}
    except (KeyError, TypeError) as exc:
        return {"error": f"Failed to parse repo response: {exc}"}


def check_issues_enabled(repo: str) -> dict:
    """Check whether a GitHub repository has issues enabled.

    Returns {"enabled": True|False} or {"error": str}.
    """
    token = get_token()
    if not token:
        return {"error": "No GitHub token found (set GITHUB_TOKEN in ~/.conforma/.env)"}

    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        if resp.status_code == 404:
            return {"error": f"Repository not found: {repo}"}
        if resp.status_code != 200:
            return {"error": f"GitHub API error {resp.status_code}"}
        return {"enabled": resp.json().get("has_issues", False)}
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}"}


def create_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> dict:
    """Create a GitHub issue via the API.

    Returns {"issue_url": str, "issue_number": int} or {"error": str}.
    """
    token = get_token()
    if not token:
        return {"error": "No GitHub token found (set GITHUB_TOKEN in ~/.conforma/.env)"}

    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels

    try:
        resp = requests.post(
            f"{GITHUB_API}/repos/{repo}/issues",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=payload,
            timeout=60,
        )
        if resp.status_code not in (201, 200):
            return {"error": f"GitHub API error {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        return {
            "issue_url": data.get("html_url", ""),
            "issue_number": data.get("number"),
        }
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}"}


def search_issues(
    repo: str,
    labels: list[str] | None = None,
    title_keywords: str | None = None,
    state: str = "open",
    max_results: int = 10,
) -> dict:
    """Search GitHub issues by label and title keywords.

    Returns {"issues": [{"url", "title", "state", "created_at", "number"}], "total": int}
    or {"error": str}.
    """
    token = get_token()
    if not token:
        return {"error": "No GitHub token found (set GITHUB_TOKEN in ~/.conforma/.env)"}

    qualifiers = [f"repo:{repo}", "is:issue", f"state:{state}"]
    if labels:
        for label in labels:
            qualifiers.append(f'label:"{label}"')
    if title_keywords:
        qualifiers.append(f"{title_keywords} in:title")

    query = " ".join(qualifiers)

    try:
        resp = requests.get(
            f"{GITHUB_API}/search/issues",
            params={"q": query, "per_page": min(max_results, 100)},
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return {"error": f"GitHub search API error {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        issues = []
        for item in data.get("items", [])[:max_results]:
            issues.append({
                "url": item.get("html_url", ""),
                "title": item.get("title", ""),
                "state": item.get("state", ""),
                "created_at": item.get("created_at", ""),
                "number": item.get("number"),
            })
        return {"issues": issues, "total": data.get("total_count", 0)}
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}"}


def check_workflow_run(repo: str, run_id: int | str) -> dict:
    """Check GitHub Actions workflow run status."""
    token = get_token()
    if not token:
        return {"error": "No GitHub token found (set GITHUB_TOKEN in ~/.conforma/.env)"}

    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/actions/runs/{run_id}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return {"error": f"GitHub API error {resp.status_code}: {resp.text[:300]}"}
        data = resp.json()
        return {
            "status": data.get("status", ""),
            "conclusion": data.get("conclusion"),
            "url": data.get("html_url", ""),
        }
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}"}
    except (KeyError, TypeError) as exc:
        return {"error": f"Failed to parse workflow run response: {exc}"}


def main() -> None:
    import konflux_environment
    konflux_environment.load()

    parser = argparse.ArgumentParser(description="GitHub primitives")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify-auth")

    p_file = sub.add_parser("get-file")
    p_file.add_argument("--repo", required=True)
    p_file.add_argument("--path", required=True)
    p_file.add_argument("--ref", default="main")

    p_repo = sub.add_parser("get-repo")
    p_repo.add_argument("--repo", required=True)

    p_pr = sub.add_parser("create-pr")
    p_pr.add_argument("--repo", required=True)
    p_pr.add_argument("--title", required=True)
    p_pr.add_argument("--body", required=True)
    p_pr.add_argument("--head", required=True)
    p_pr.add_argument("--base", default="main")

    p_issues_enabled = sub.add_parser("check-issues-enabled")
    p_issues_enabled.add_argument("--repo", required=True)

    p_issue = sub.add_parser("create-issue")
    p_issue.add_argument("--repo", required=True)
    p_issue.add_argument("--title", required=True)
    p_issue.add_argument("--body", required=True)
    p_issue.add_argument("--label", action="append", default=None, dest="labels")

    p_search = sub.add_parser("search-issues")
    p_search.add_argument("--repo", required=True)
    p_search.add_argument("--label", action="append", default=None, dest="labels")
    p_search.add_argument("--title-keywords", default=None)
    p_search.add_argument("--state", default="open", choices=["open", "closed"])
    p_search.add_argument("--max-results", type=int, default=10)

    p_run = sub.add_parser("check-workflow-run")
    p_run.add_argument("--repo", required=True)
    p_run.add_argument("--run-id", required=True)

    args = parser.parse_args()

    if args.command == "verify-auth":
        result = verify_auth()
    elif args.command == "get-file":
        result = get_file(args.repo, args.path, ref=args.ref)
    elif args.command == "get-repo":
        result = get_repo(args.repo)
    elif args.command == "create-pr":
        result = create_pr(args.repo, args.title, args.body, args.head, base_branch=args.base)
    elif args.command == "check-issues-enabled":
        result = check_issues_enabled(args.repo)
    elif args.command == "create-issue":
        result = create_issue(args.repo, args.title, args.body, labels=args.labels)
    elif args.command == "search-issues":
        result = search_issues(
            args.repo, labels=args.labels,
            title_keywords=args.title_keywords,
            state=args.state, max_results=args.max_results,
        )
    elif args.command == "check-workflow-run":
        result = check_workflow_run(args.repo, args.run_id)
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
