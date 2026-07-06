"""submit_feedback — submit_feedback.py -- Conforma feedback issue submission workflow.

PUBLIC API:
    classify_error() -> dict  [line 65]
    from_error() -> dict  [line 104]
    search_existing(repo_path, plat, labels, title_keywords, host) -> dict  [line 178]
    detect(cwd, remote) -> dict  [line 202]
    check_issues(repo_path, plat, host) -> dict  [line 210]
    gather_context() -> dict  [line 222]
    submit(repo_path, plat, title, body, labels, host) -> dict  [line 286]
    parse_args(argv) -> argparse.Namespace  [line 307]
    main(argv) -> None  [line 367]

INTERNAL SECTIONS:
    Main: _load_template, _load_known_patterns

DEPENDENCIES: argparse, git_ops, github_ops, gitlab_ops, json, pathlib, platform, sys, yaml

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
_KNOWN_ERRORS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "references" / "known-infra-errors.yaml"
)


def _load_template() -> dict:
    """Load the feedback template YAML."""
    with _TEMPLATE_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_known_patterns() -> list[dict]:
    """Load known infrastructure error patterns from YAML."""
    if not _KNOWN_ERRORS_PATH.exists():
        return []
    with _KNOWN_ERRORS_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("patterns", [])


def classify_error(
    *,
    exception_type: str,
    error_message: str,
    script_path: str,
) -> dict:
    """Match an error against known infrastructure patterns.

    Returns {"classified": True, "pattern_id", "affected_skill", "severity",
             "title_hint", "notes"} on match, or {"classified": False}.
    """
    patterns = _load_known_patterns()
    msg_lower = error_message.lower()

    for pat in patterns:
        allowed_types = pat.get("exception_type", [])
        if exception_type not in allowed_types:
            continue

        keywords = pat.get("message_keywords", [])
        if not all(kw.lower() in msg_lower for kw in keywords):
            continue

        script_kws = pat.get("script_keywords", [])
        if script_kws and not any(sk in script_path for sk in script_kws):
            continue

        return {
            "classified": True,
            "pattern_id": pat["id"],
            "affected_skill": pat.get("affected_skill", "*"),
            "severity": pat.get("severity", "major"),
            "title_hint": pat.get("title_hint", ""),
            "notes": pat.get("notes", ""),
        }

    return {"classified": False}


def from_error(
    *,
    skill_name: str,
    workflow_step: str,
    script_path: str,
    error_type: str,
    error_message: str,
    traceback: str = "N/A",
    reproduction_command: str = "N/A",
    severity: str = "major",
    root_cause: str | None = None,
    title_hint: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Build an infrastructure issue from error context.

    Returns {"title", "body", "labels", "platform", "repo_path", "host",
             "python_version", "os_info"} or {"error"}.
    """
    remote_info = detect(cwd=cwd)
    if "error" in remote_info:
        return remote_info

    tmpl = _load_template()
    infra = tmpl.get("infra_issue", {})
    title_template = infra.get("title_template", "[infra] {skill_name}: {title_hint}")
    body_template = infra.get("body_template", "")
    labels = list(infra.get("labels", []))

    if root_cause:
        root_cause_section = (
            "## Root Cause Analysis (AI-generated, may need verification)\n\n"
            + root_cause
        )
    else:
        root_cause_section = ""

    hint = title_hint or error_type
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    os_info = f"{platform.system()} {platform.release()}"

    fields = {
        "skill_name": skill_name,
        "workflow_step": workflow_step,
        "script_path": script_path,
        "error_type": error_type,
        "error_message": error_message,
        "traceback": traceback,
        "reproduction_command": reproduction_command,
        "severity": severity,
        "root_cause_section": root_cause_section,
        "title_hint": hint,
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


def search_existing(
    repo_path: str,
    plat: str,
    labels: list[str] | None = None,
    title_keywords: str | None = None,
    host: str | None = None,
) -> dict:
    """Search for existing open issues that may be duplicates.

    Returns {"matches": [...], "total": int} or {"error": str}.
    """
    if plat == "github":
        result = github_ops.search_issues(
            repo_path, labels=labels, title_keywords=title_keywords,
        )
        if "error" in result:
            return result
        return {
            "matches": result.get("issues", []),
            "total": result.get("total", 0),
        }
    return {"matches": [], "total": 0}


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

    p_classify = sub.add_parser("classify-error")
    p_classify.add_argument("--exception-type", required=True)
    p_classify.add_argument("--error-message", required=True)
    p_classify.add_argument("--script-path", required=True)

    p_from = sub.add_parser("from-error")
    p_from.add_argument("--skill-name", required=True)
    p_from.add_argument("--workflow-step", required=True)
    p_from.add_argument("--script-path", required=True)
    p_from.add_argument("--error-type", required=True)
    p_from.add_argument("--error-message", required=True)
    p_from.add_argument("--traceback", default="N/A")
    p_from.add_argument("--reproduction-command", default="N/A")
    p_from.add_argument("--severity", default="major", choices=["critical", "major", "minor", "cosmetic"])
    p_from.add_argument("--root-cause", default=None)
    p_from.add_argument("--title-hint", default=None)
    p_from.add_argument("--cwd", default=None)

    p_search_ex = sub.add_parser("search-existing")
    p_search_ex.add_argument("--repo-path", required=True)
    p_search_ex.add_argument("--platform", required=True, choices=["github", "gitlab"])
    p_search_ex.add_argument("--label", action="append", default=None, dest="labels")
    p_search_ex.add_argument("--title-keywords", default=None)
    p_search_ex.add_argument("--host", default=None)

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
    elif args.command == "classify-error":
        result = classify_error(
            exception_type=args.exception_type,
            error_message=args.error_message,
            script_path=args.script_path,
        )
    elif args.command == "from-error":
        result = from_error(
            skill_name=args.skill_name,
            workflow_step=args.workflow_step,
            script_path=args.script_path,
            error_type=args.error_type,
            error_message=args.error_message,
            traceback=args.traceback,
            reproduction_command=args.reproduction_command,
            severity=args.severity,
            root_cause=args.root_cause,
            title_hint=args.title_hint,
            cwd=args.cwd,
        )
    elif args.command == "search-existing":
        result = search_existing(
            args.repo_path,
            args.platform,
            labels=args.labels,
            title_keywords=args.title_keywords,
            host=args.host,
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
