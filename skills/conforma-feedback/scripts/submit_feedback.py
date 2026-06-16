"""submit_feedback.py -- Conforma feedback issue submission workflow.

Subcommands:
    detect          Detect hosting platform from git remote
    check-issues    Verify the target repo has issues enabled
    gather-context  Build issue title, body, and labels from user input
    submit          Create the issue on the detected platform

Usage:
    python3 submit_feedback.py detect [--remote origin] [--cwd .]
    python3 submit_feedback.py check-issues --repo-path ORG/REPO --platform github|gitlab [--host HOST]
    python3 submit_feedback.py gather-context --skill-name NAME --type bug|enhancement \\
        --summary TEXT --expected TEXT --actual TEXT [--error-output TEXT] \\
        [--severity critical|major|minor|cosmetic] [--additional-context TEXT] [--cwd .]
    python3 submit_feedback.py submit --repo-path ORG/REPO --platform github|gitlab \\
        --title TEXT --body TEXT [--label LABEL ...] [--host HOST]
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import _setup_env  # noqa: F401

import git_ops
import github_ops
import gitlab_ops
import yaml


_TEMPLATE_PATH = Path(__file__).resolve().parent / "feedback_template.yaml"


def _load_template() -> dict:
    """Load the feedback template YAML."""
    with _TEMPLATE_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def detect(cwd: str | None = None, remote: str = "origin") -> dict:
    """Detect the hosting platform from a git remote.

    Returns {"platform", "repo_path", "host", "url"} or {"error"}.
    """
    return git_ops.detect_remote(cwd=cwd, remote=remote)


def check_issues(repo_path: str, plat: str, host: str | None = None) -> dict:
    """Check whether the target repository has issues enabled.

    Returns {"enabled": bool} or {"error": str}.
    """
    if plat == "github":
        return github_ops.check_issues_enabled(repo_path)
    elif plat == "gitlab":
        return gitlab_ops.check_issues_enabled(repo_path, instance_url=host)
    return {"error": f"Unsupported platform: {plat}"}


def gather_context(
    *,
    skill_name: str,
    issue_type: str,
    summary: str,
    expected: str,
    actual: str,
    error_output: str = "N/A",
    severity: str = "major",
    additional_context: str = "N/A",
    cwd: str | None = None,
) -> dict:
    """Assemble issue title, body, and labels from gathered information.

    Returns {"title", "body", "labels", "platform", "repo_path", "host",
             "python_version", "os_info"} or {"error"}.
    """
    remote_info = detect(cwd=cwd)
    if "error" in remote_info:
        return remote_info

    tmpl = _load_template()
    title_template = tmpl.get("title_template", "[conforma-feedback] {issue_type}: {summary}")
    body_template = tmpl.get("body_template", "")
    label_config = tmpl.get("labels", {})

    labels = list(label_config.get("always", []))
    type_labels = label_config.get(issue_type, [])
    labels.extend(type_labels)

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    os_info = f"{platform.system()} {platform.release()}"

    fields = {
        "skill_name": skill_name,
        "issue_type": issue_type,
        "summary": summary,
        "expected": expected,
        "actual": actual,
        "error_output": error_output,
        "severity": severity,
        "additional_context": additional_context,
        "python_version": python_version,
        "os_info": os_info,
        "platform": remote_info["platform"],
        "host": remote_info["host"],
        "repo_path": remote_info["repo_path"],
    }

    title = title_template.format(**fields)
    body = body_template.format(**fields)

    return {
        "title": title,
        "body": body,
        "labels": labels,
        "platform": remote_info["platform"],
        "repo_path": remote_info["repo_path"],
        "host": remote_info["host"],
        "python_version": python_version,
        "os_info": os_info,
    }


def submit(
    repo_path: str,
    plat: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
    host: str | None = None,
) -> dict:
    """Create an issue on the detected platform.

    Returns {"issue_url": str, ...} or {"error": str}.
    """
    if plat == "github":
        return github_ops.create_issue(repo_path, title, body, labels=labels)
    elif plat == "gitlab":
        return gitlab_ops.create_issue(
            repo_path, title, body, labels=labels, instance_url=host,
        )
    return {"error": f"Unsupported platform: {plat}"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Conforma feedback issue submission")
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect")
    p_detect.add_argument("--remote", default="origin")
    p_detect.add_argument("--cwd", default=None)

    p_check = sub.add_parser("check-issues")
    p_check.add_argument("--repo-path", required=True)
    p_check.add_argument("--platform", required=True, choices=["github", "gitlab"])
    p_check.add_argument("--host", default=None)

    p_gather = sub.add_parser("gather-context")
    p_gather.add_argument("--skill-name", required=True)
    p_gather.add_argument("--type", required=True, choices=["bug", "enhancement"], dest="issue_type")
    p_gather.add_argument("--summary", required=True)
    p_gather.add_argument("--expected", required=True)
    p_gather.add_argument("--actual", required=True)
    p_gather.add_argument("--error-output", default="N/A")
    p_gather.add_argument("--severity", default="major", choices=["critical", "major", "minor", "cosmetic"])
    p_gather.add_argument("--additional-context", default="N/A")
    p_gather.add_argument("--cwd", default=None)

    p_submit = sub.add_parser("submit")
    p_submit.add_argument("--repo-path", required=True)
    p_submit.add_argument("--platform", required=True, choices=["github", "gitlab"])
    p_submit.add_argument("--title", required=True)
    p_submit.add_argument("--body", required=True)
    p_submit.add_argument("--label", action="append", default=None, dest="labels")
    p_submit.add_argument("--host", default=None)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.command == "detect":
        result = detect(cwd=args.cwd, remote=args.remote)
    elif args.command == "check-issues":
        result = check_issues(args.repo_path, args.platform, host=args.host)
    elif args.command == "gather-context":
        result = gather_context(
            skill_name=args.skill_name,
            issue_type=args.issue_type,
            summary=args.summary,
            expected=args.expected,
            actual=args.actual,
            error_output=args.error_output,
            severity=args.severity,
            additional_context=args.additional_context,
            cwd=args.cwd,
        )
    elif args.command == "submit":
        result = submit(
            args.repo_path,
            args.platform,
            args.title,
            args.body,
            labels=args.labels,
            host=args.host,
        )
    else:
        print(json.dumps({"error": f"Unknown command: {args.command}"}))
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
