"""gitlab_ops.py -- GitLab primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import warnings
from pathlib import Path
from urllib.parse import urlparse

import gitlab
import yaml
from gitlab.exceptions import GitlabAuthenticationError, GitlabError, GitlabGetError

DEFAULT_INSTANCE_HOST = "gitlab.cee.redhat.com"
GLAB_CONFIG_PATH = Path.home() / ".config" / "glab-cli" / "config.yml"


def _get_instance_host() -> str:
    return os.environ.get("GITLAB_HOST") or os.environ.get("GL_HOST") or DEFAULT_INSTANCE_HOST


def _normalize_instance_url(instance_url: str | None) -> str:
    raw = instance_url if instance_url is not None else _get_instance_host()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.rstrip("/")
    return f"https://{raw}".rstrip("/")


def _host_from_url(instance_url: str) -> str:
    parsed = urlparse(instance_url)
    return parsed.netloc or instance_url.removeprefix("https://").removeprefix("http://").rstrip("/")


def _ssl_verify() -> bool:
    val = os.environ.get("GITLAB_SSL_VERIFY", "true").strip().lower()
    skip = val in ("0", "false", "no", "off")
    if skip:
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    return not skip


def discover_token(instance_url: str | None = None) -> str | None:
    """Discover GitLab token from GITLAB_TOKEN env or glab config."""
    token = os.environ.get("GITLAB_TOKEN")
    if token:
        return token

    if not GLAB_CONFIG_PATH.exists():
        return None

    url = _normalize_instance_url(instance_url)
    host = _host_from_url(url)
    try:
        with GLAB_CONFIG_PATH.open(encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        hosts = config.get("hosts", {})
        host_config = hosts.get(host, {})
        if isinstance(host_config, dict):
            return host_config.get("token") or host_config.get("oauth_token")
    except (OSError, yaml.YAMLError):
        return None
    return None


def get_client(instance_url: str | None = None, token: str | None = None) -> gitlab.Gitlab:
    """Get authenticated GitLab client."""
    url = _normalize_instance_url(instance_url)
    resolved_token = token or discover_token(url)
    if not resolved_token:
        raise ValueError(
            "GitLab token not found. Set GITLAB_TOKEN or configure glab "
            f"(~/.config/glab-cli/config.yml) for {_host_from_url(url)}"
        )

    gl = gitlab.Gitlab(url=url, private_token=resolved_token, ssl_verify=_ssl_verify())
    gl.auth()
    return gl


def verify_auth(instance_url: str | None = None) -> dict:
    """Check GitLab auth works."""
    url = _normalize_instance_url(instance_url)
    try:
        gl = get_client(instance_url=url)
        user = gl.user.username if gl.user else None
        return {"ok": True, "user": user, "instance": url, "error": None}
    except GitlabAuthenticationError as exc:
        return {"ok": False, "user": None, "instance": url, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "user": None, "instance": url, "error": str(exc)}


def get_project(project_path: str, instance_url: str | None = None) -> dict:
    """Get project info."""
    try:
        gl = get_client(instance_url=instance_url)
        project = gl.projects.get(project_path)
        return {
            "id": project.id,
            "path": project.path_with_namespace,
            "url": project.web_url,
        }
    except GitlabGetError as exc:
        return {"error": f"Project not found or inaccessible: {project_path}: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def _authenticated_clone_url(http_url: str, token: str) -> str:
    parsed = urlparse(http_url)
    return f"{parsed.scheme}://oauth2:{token}@{parsed.netloc}{parsed.path}"


def clone_repo(
    project_path: str,
    target_dir: str,
    branch: str | None = None,
    instance_url: str | None = None,
) -> dict:
    """Clone a GitLab repo with an authenticated URL."""
    url = _normalize_instance_url(instance_url)
    try:
        token = discover_token(url)
        if not token:
            return {"error": "GitLab token not found for clone"}

        gl = get_client(instance_url=url, token=token)
        project = gl.projects.get(project_path)
        clone_branch = branch or project.default_branch
        auth_url = _authenticated_clone_url(project.http_url_to_repo, token)

        target = Path(target_dir)
        if target.exists() and any(target.iterdir()):
            return {"error": f"Target directory is not empty: {target_dir}"}

        cmd = ["git", "clone", "--branch", clone_branch, auth_url, str(target)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return {"error": f"git clone failed: {detail}"}

        return {"path": str(target.resolve()), "branch": clone_branch}
    except GitlabGetError as exc:
        return {"error": f"Project not found: {project_path}: {exc}"}
    except subprocess.TimeoutExpired:
        return {"error": "git clone timed out"}
    except Exception as exc:
        return {"error": str(exc)}


def _run_git(repo_dir: str, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def push_branch(
    repo_dir: str,
    branch: str,
    commit_msg: str,
    files: list[str] | None = None,
) -> dict:
    """Stage files (or all), commit, and push a branch."""
    repo_path = Path(repo_dir)
    if not repo_path.is_dir():
        return {"error": f"Repository directory not found: {repo_dir}"}

    try:
        checkout = _run_git(str(repo_path), ["checkout", "-B", branch])
        if checkout.returncode != 0:
            return {"error": f"git checkout failed: {checkout.stderr.strip()}"}

        if files:
            add = _run_git(str(repo_path), ["add", *files])
        else:
            add = _run_git(str(repo_path), ["add", "-A"])
        if add.returncode != 0:
            return {"error": f"git add failed: {add.stderr.strip()}"}

        status = _run_git(str(repo_path), ["status", "--porcelain"])
        if status.returncode != 0:
            return {"error": f"git status failed: {status.stderr.strip()}"}
        if not status.stdout.strip():
            return {"error": "No changes to commit"}

        commit = _run_git(str(repo_path), ["commit", "-m", commit_msg])
        if commit.returncode != 0:
            return {"error": f"git commit failed: {commit.stderr.strip()}"}

        push = _run_git(str(repo_path), ["push", "-u", "origin", branch], timeout=300)
        if push.returncode != 0:
            return {"error": f"git push failed: {push.stderr.strip()}"}

        return {"branch": branch, "pushed": True}
    except subprocess.TimeoutExpired:
        return {"error": "git operation timed out"}
    except Exception as exc:
        return {"error": str(exc)}


def create_mr(
    project_path: str,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str = "",
    instance_url: str | None = None,
) -> dict:
    """Create a merge request on the given project."""
    try:
        gl = get_client(instance_url=instance_url)
        project = gl.projects.get(project_path)
        mr = project.mergerequests.create(
            {
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
            }
        )
        return {"mr_url": mr.web_url, "mr_iid": mr.iid}
    except GitlabError as exc:
        return {"error": f"Failed to create merge request: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def update_mr(
    project_path: str,
    mr_iid: int,
    title: str | None = None,
    description: str | None = None,
    instance_url: str | None = None,
) -> dict:
    """Update merge request title and/or description."""
    if title is None and description is None:
        return {"error": "At least one of title or description must be provided"}

    try:
        gl = get_client(instance_url=instance_url)
        project = gl.projects.get(project_path)
        mr = project.mergerequests.get(mr_iid)
        if title is not None:
            mr.title = title
        if description is not None:
            mr.description = description
        mr.save()
        return {"mr_url": mr.web_url, "mr_iid": mr.iid}
    except GitlabGetError as exc:
        return {"error": f"Merge request not found: {mr_iid}: {exc}"}
    except GitlabError as exc:
        return {"error": f"Failed to update merge request: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def find_mr(
    project_path: str,
    source_branch: str | None = None,
    target_branch: str | None = None,
    state: str = "opened",
    instance_url: str | None = None,
) -> list[dict]:
    """Search merge requests on a project."""
    try:
        gl = get_client(instance_url=instance_url)
        project = gl.projects.get(project_path)
        params: dict[str, str] = {"state": state, "all": True}
        if source_branch:
            params["source_branch"] = source_branch
        if target_branch:
            params["target_branch"] = target_branch

        mrs = project.mergerequests.list(**params)
        return [
            {
                "mr_iid": mr.iid,
                "mr_url": mr.web_url,
                "title": mr.title,
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
                "state": mr.state,
            }
            for mr in mrs
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


def main() -> None:
    parser = argparse.ArgumentParser(description="GitLab primitives")
    parser.add_argument("--instance-url", default=None, help="GitLab instance URL or host")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify-auth")

    p_project = sub.add_parser("get-project")
    p_project.add_argument("--project", required=True)

    p_clone = sub.add_parser("clone-repo")
    p_clone.add_argument("--project", required=True)
    p_clone.add_argument("--target-dir", required=True)
    p_clone.add_argument("--branch", default=None)

    p_push = sub.add_parser("push-branch")
    p_push.add_argument("--repo-dir", required=True)
    p_push.add_argument("--branch", required=True)
    p_push.add_argument("--commit-msg", required=True)
    p_push.add_argument("--files", nargs="*", default=None)

    p_create = sub.add_parser("create-mr")
    p_create.add_argument("--project", required=True)
    p_create.add_argument("--source-branch", required=True)
    p_create.add_argument("--target-branch", default="main")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--description", default="")

    p_find = sub.add_parser("find-mr")
    p_find.add_argument("--project", required=True)
    p_find.add_argument("--source-branch", default=None)
    p_find.add_argument("--target-branch", default=None)
    p_find.add_argument("--state", default="opened")

    args = parser.parse_args()
    instance_url = args.instance_url

    if args.command == "verify-auth":
        result = verify_auth(instance_url=instance_url)
    elif args.command == "get-project":
        result = get_project(args.project, instance_url=instance_url)
    elif args.command == "clone-repo":
        result = clone_repo(args.project, args.target_dir, branch=args.branch, instance_url=instance_url)
    elif args.command == "push-branch":
        result = push_branch(args.repo_dir, args.branch, args.commit_msg, files=args.files)
    elif args.command == "create-mr":
        result = create_mr(
            args.project,
            args.source_branch,
            args.target_branch,
            args.title,
            description=args.description,
            instance_url=instance_url,
        )
    elif args.command == "find-mr":
        result = find_mr(
            args.project,
            source_branch=args.source_branch,
            target_branch=args.target_branch,
            state=args.state,
            instance_url=instance_url,
        )
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
