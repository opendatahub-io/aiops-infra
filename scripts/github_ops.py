"""github_ops.py -- GitHub primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess

import requests

GITHUB_API = "https://api.github.com"


def _run_gh(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_token() -> str:
    """Get GitHub token from gh auth token."""
    try:
        result = _run_gh(["auth", "token"], timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def verify_auth() -> dict:
    """Check gh CLI authentication."""
    try:
        status = _run_gh(["auth", "status"], timeout=15)
        if status.returncode != 0:
            detail = (status.stderr + status.stdout).strip()
            return {"ok": False, "user": None, "error": detail or "gh auth status failed"}

        user_result = _run_gh(["api", "user", "--jq", ".login"], timeout=15)
        if user_result.returncode != 0:
            detail = (user_result.stderr + user_result.stdout).strip()
            return {"ok": False, "user": None, "error": detail or "Failed to fetch GitHub user"}

        user = user_result.stdout.strip() or None
        return {"ok": True, "user": user, "error": None}
    except FileNotFoundError:
        return {
            "ok": False,
            "user": None,
            "error": "gh CLI not found on PATH. Install from https://cli.github.com/",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "user": None, "error": "gh command timed out"}
    except Exception as exc:
        return {"ok": False, "user": None, "error": str(exc)}


def create_pr(
    repo: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main",
) -> dict:
    """Create a pull request via gh pr create."""
    try:
        result = _run_gh(
            [
                "pr",
                "create",
                "--repo",
                repo,
                "--title",
                title,
                "--body",
                body,
                "--head",
                head_branch,
                "--base",
                base_branch,
            ],
            timeout=60,
        )
        if result.returncode != 0:
            detail = (result.stderr + result.stdout).strip()
            return {"error": detail or "gh pr create failed"}

        pr_url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        pr_number = None
        if pr_url:
            match = re.search(r"/pull/(\d+)(?:\?.*)?$", pr_url)
            if match:
                pr_number = int(match.group(1))

        if pr_number is None:
            lookup = _run_gh(
                [
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--head",
                    head_branch,
                    "--base",
                    base_branch,
                    "--state",
                    "open",
                    "--json",
                    "url,number",
                    "--limit",
                    "1",
                ],
                timeout=30,
            )
            if lookup.returncode == 0 and lookup.stdout.strip():
                data = json.loads(lookup.stdout)
                if data:
                    pr_url = data[0].get("url", pr_url)
                    pr_number = data[0].get("number")

        if not pr_url or pr_number is None:
            return {"error": "PR created but could not determine PR URL/number"}

        return {"pr_url": pr_url, "pr_number": pr_number}
    except FileNotFoundError:
        return {"error": "gh CLI not found on PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "gh pr create timed out"}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return {"error": f"Failed to parse PR response: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def get_file(repo: str, path: str, ref: str = "main") -> dict:
    """Get file content via GitHub API."""
    token = get_token()
    if not token:
        return {"error": "Failed to get GitHub token from 'gh auth token'"}

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
    """Get repository metadata via gh api."""
    try:
        result = _run_gh(
            [
                "api",
                f"repos/{repo}",
                "--jq",
                "{full_name: .full_name, default_branch: .default_branch, private: .private}",
            ],
            timeout=30,
        )
        if result.returncode != 0:
            detail = (result.stderr + result.stdout).strip()
            return {"error": detail or f"Failed to fetch repo {repo}"}

        data = json.loads(result.stdout)
        return {
            "full_name": data["full_name"],
            "default_branch": data["default_branch"],
            "private": bool(data["private"]),
        }
    except FileNotFoundError:
        return {"error": "gh CLI not found on PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "gh api timed out"}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return {"error": f"Failed to parse repo response: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def check_workflow_run(repo: str, run_id: int | str) -> dict:
    """Check GitHub Actions workflow run status."""
    try:
        result = _run_gh(
            [
                "api",
                f"repos/{repo}/actions/runs/{run_id}",
                "--jq",
                "{status: .status, conclusion: .conclusion, url: .html_url}",
            ],
            timeout=30,
        )
        if result.returncode != 0:
            detail = (result.stderr + result.stdout).strip()
            return {"error": detail or f"Failed to fetch workflow run {run_id}"}

        data = json.loads(result.stdout)
        return {
            "status": data.get("status", ""),
            "conclusion": data.get("conclusion"),
            "url": data.get("url", ""),
        }
    except FileNotFoundError:
        return {"error": "gh CLI not found on PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "gh api timed out"}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return {"error": f"Failed to parse workflow run response: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def main() -> None:
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
    elif args.command == "check-workflow-run":
        result = check_workflow_run(args.repo, args.run_id)
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
