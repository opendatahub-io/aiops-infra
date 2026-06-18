#!/usr/bin/env python3
"""Verify all prerequisites for running the conforma-analyze workflow.

Checks (in order):
  1. Python dependencies (requests, yaml, gitlab, jira)
  2. .work/.env file (secrets: tokens, credentials)
  3. GitLab (GITLAB_HOST + VPN + token for konflux-release-data)
  4. Konflux (KONFLUX_TENANT + KONFLUX_CLUSTER_DOMAIN auto-discovery)
  5. GitHub authentication (private conforma-reporter access)
  6. Jira authentication (API token + email for coverage search)
  7. Slack authentication (slackdump binary + session) — OPTIONAL

Slack is optional. The workflow can proceed without it — the violation coverage
table will not include links to related Slack discussions about violations.

Exit codes:
  0 — all required checks pass (optional checks may show warnings)
  1 — one or more required checks failed (details printed)

Usage:
    python3 scripts/verify_conforma_prerequisites.py
    python3 scripts/verify_conforma_prerequisites.py --json
    python3 scripts/verify_conforma_prerequisites.py --fix  # print fix instructions
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path

_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import konflux_environment  # noqa: E402

konflux_environment.load()

REPO_ROOT = Path(__file__).resolve().parent.parent


def _check_python_deps() -> dict:
    """Check that all required Python packages are importable."""
    required = ["requests", "yaml", "gitlab", "jira"]
    missing = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)

    if missing:
        return {
            "ok": False,
            "name": "python_deps",
            "error": f"Missing Python packages: {', '.join(missing)}",
            "fix": "Run: uv sync  (or: pip install -e .)",
        }
    return {"ok": True, "name": "python_deps", "error": None, "fix": None, "detail": "All installed"}


def _check_konflux() -> dict:
    """Check that Konflux tenant is configured (KONFLUX_TENANT, KONFLUX_CLUSTER_DOMAIN).

    Primary path: user provides KONFLUX_TENANT in .work/.env alongside GITLAB_HOST,
    then KONFLUX_CLUSTER_DOMAIN is auto-discovered by konflux_tenant_env_discovery.py.

    Auto-discovery depends on GitLab auth. If GitLab is not configured, this
    check reports the dependency rather than a generic "discovery failed".
    """
    has_tenant = bool(os.environ.get("KONFLUX_TENANT"))
    has_cluster_domain = bool(os.environ.get("KONFLUX_CLUSTER_DOMAIN"))

    if has_tenant and has_cluster_domain:
        cluster_domain = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
        cluster_id = cluster_domain.split(".")[0] if cluster_domain else ""
        detail = f"Cluster: {cluster_id}" if cluster_id else None
        return {"ok": True, "name": "konflux", "error": None, "fix": None, "detail": detail}

    if not has_tenant:
        return {
            "ok": False,
            "name": "konflux",
            "error": "KONFLUX_TENANT not set",
            "fix": (
                "Add to .work/.env:\n"
                "  KONFLUX_TENANT=your-konflux-tenant-name\n"
                "Then re-run — KONFLUX_CLUSTER_DOMAIN will be auto-discovered."
            ),
        }

    # KONFLUX_TENANT is set but CLUSTER_DOMAIN is missing — discovery didn't work.
    # Distinguish "blocked by gitlab" from a discovery-specific failure.
    host = os.environ.get("GITLAB_HOST", "")
    if not host:
        return {
            "ok": False,
            "name": "konflux",
            "error": "Blocked by gitlab — GITLAB_HOST not set (required for auto-discovery)",
            "fix": "Fix the gitlab check first, then re-run. KONFLUX_CLUSTER_DOMAIN will auto-discover.",
        }

    try:
        import gitlab_ops
        token = gitlab_ops.discover_token(f"https://{host}")
    except Exception:
        token = os.environ.get("GITLAB_TOKEN")

    if not token:
        return {
            "ok": False,
            "name": "konflux",
            "error": "Blocked by gitlab — no token (required for auto-discovery)",
            "fix": "Fix the gitlab check first, then re-run. KONFLUX_CLUSTER_DOMAIN will auto-discover.",
        }

    # GitLab looks OK — try discovery directly to get the specific failure reason.
    tenant = os.environ.get("KONFLUX_TENANT", "")
    preferred = os.environ.get("PREFERRED_KONFLUX_CLUSTER")
    try:
        import konflux_tenant_env_discovery
        konflux_tenant_env_discovery.discover(tenant, preferred_cluster=preferred)
        # If this succeeds, CLUSTER_DOMAIN should now be set (via load's cache).
        # Shouldn't normally reach here since load() already tried, but handle it.
        return {"ok": True, "name": "konflux", "error": None, "fix": None}
    except Exception as exc:
        error_msg = str(exc)
        # Provide actionable fix based on the specific error.
        if "multiple clusters" in error_msg.lower():
            return {
                "ok": False,
                "name": "konflux",
                "error": error_msg,
                "fix": (
                    "Add to .work/.env:\n"
                    "  PREFERRED_KONFLUX_CLUSTER=your-cluster-id"
                ),
            }
        return {
            "ok": False,
            "name": "konflux",
            "error": f"Auto-discovery failed: {error_msg}",
            "fix": (
                "Retry discovery:\n"
                "  python3 scripts/konflux_tenant_env_discovery.py --tenant $KONFLUX_TENANT --human\n"
                "If discovery cannot work in your environment, add manually to .work/.env:\n"
                "  KONFLUX_CLUSTER_DOMAIN=your-cluster-domain"
            ),
        }


def _check_dotenv() -> dict:
    """Check that .work/.env exists."""
    dotenv_path = REPO_ROOT / ".work" / ".env"
    if not dotenv_path.is_file():
        return {
            "ok": False,
            "name": "dotenv",
            "error": ".work/.env not found",
            "fix": "Run: cp .work/.env.example .work/.env  (then fill in tokens)",
        }
    return {"ok": True, "name": "dotenv", "error": None, "fix": None, "detail": ".work/.env"}


def _check_github_auth() -> dict:
    """Check GitHub authentication."""
    import github_ops

    result = github_ops.verify_auth()
    if result["ok"]:
        return {
            "ok": True,
            "name": "github",
            "error": None,
            "fix": None,
            "detail": f"Authenticated as: {result['user']}",
        }
    return {
        "ok": False,
        "name": "github",
        "error": result["error"],
        "fix": (
            "Create a Personal Access Token (https://github.com/settings/tokens/new)"
            " with scope: repo (for private repos)"
            " and add to .work/.env:\n"
            "  GITHUB_TOKEN=ghp_your_token_here"
        ),
    }


def _check_gitlab_auth() -> dict:
    """Check GitLab host and authentication."""
    host = os.environ.get("GITLAB_HOST", "")
    if not host:
        return {
            "ok": False,
            "name": "gitlab",
            "error": "GITLAB_HOST not set",
            "fix": (
                "Add to .work/.env:\n"
                "  GITLAB_HOST=your-gitlab-host"
            ),
        }

    import gitlab_ops

    result = gitlab_ops.verify_auth(instance_url=f"https://{host}")
    if result.get("ok"):
        return {
            "ok": True,
            "name": "gitlab",
            "error": None,
            "fix": None,
            "detail": f"Authenticated as: {result.get('user')}",
        }
    token_url = f"https://{host}/-/user_settings/personal_access_tokens"
    return {
        "ok": False,
        "name": "gitlab",
        "error": result.get("error", "Unknown error"),
        "fix": (
            f"Ensure VPN is connected, then create a Personal Access Token ({token_url})"
            f" with scopes: api, read_repository, write_repository"
            f" and add to .work/.env:\n"
            f"  GITLAB_TOKEN=glpat-your_token_here"
        ),
    }


def _check_jira_auth() -> dict:
    """Check Jira authentication."""
    import jira_ops

    result = jira_ops.verify_auth()
    if result.get("ok"):
        return {
            "ok": True,
            "name": "jira",
            "error": None,
            "fix": None,
            "detail": f"Authenticated as: {result.get('user')}",
        }
    return {
        "ok": False,
        "name": "jira",
        "error": result.get("error", "Unknown error"),
        "fix": (
            "Create an API token (https://id.atlassian.com/manage-profile/security/api-tokens)"
            " and add to .work/.env (JIRA_EMAIL auto-derives on first successful auth):\n"
            "  JIRA_API_TOKEN=your_jira_api_token\n"
            "  JIRA_EMAIL=you@redhat.com"
        ),
    }


def _check_slack_auth() -> dict:
    """Check Slack (slackdump) authentication. Marked optional — more complex setup."""
    import slack_ops

    result = slack_ops.verify_auth()
    if result.get("ok"):
        return {
            "ok": True,
            "name": "slack",
            "optional": True,
            "error": None,
            "fix": None,
            "detail": f"Workspace: {result.get('team')} ({result.get('team_url', '')})",
        }

    error = result.get("error", "Unknown error")
    if "not found" in error.lower() or "not installed" in error.lower():
        return {
            "ok": False,
            "name": "slack",
            "optional": True,
            "error": "slackdump is not installed.",
            "fix": (
                "Without Slack the Conforma Report is produced as normal but "
                "it's missing links to Slack conversations that might be "
                "related to the Conforma Violations."
            ),
        }
    return {
        "ok": False,
        "name": "slack",
        "optional": True,
        "error": "No Slack auth credentials found.",
        "fix": (
            "Without Slack the Conforma Report is produced as normal but "
            "it's missing links to Slack conversations that might be "
            "related to the Conforma Violations."
        ),
    }


def run_all_checks() -> list[dict]:
    """Run all prerequisite checks and return results."""
    checks = [
        _check_python_deps,
        _check_dotenv,
        _check_gitlab_auth,
        _check_konflux,
        _check_github_auth,
        _check_jira_auth,
        _check_slack_auth,
    ]
    results = []
    for check_fn in checks:
        try:
            results.append(check_fn())
        except Exception as exc:
            results.append({
                "ok": False,
                "name": check_fn.__name__.replace("_check_", ""),
                "error": f"Check raised exception: {exc}",
                "fix": None,
            })
    return results


def _is_code_line(line: str) -> bool:
    """Heuristic: line looks like a KEY=value assignment or shell command."""
    stripped = line.strip()
    if re.match(r"^[A-Z_]+=", stripped):
        return True
    if re.match(r"^(echo|python3|bash|Run:|cp |pip |uv )", stripped):
        return True
    return False


def _format_fix_markdown(fix_text: str) -> str:
    """Split fix text into prose paragraphs and fenced code blocks."""
    lines = fix_text.split("\n")
    parts: list[str] = []
    code_lines: list[str] = []

    def flush_code():
        if code_lines:
            parts.append("```bash\n" + "\n".join(code_lines) + "\n```")
            code_lines.clear()

    for line in lines:
        stripped = line.strip()
        if _is_code_line(stripped):
            code_lines.append(stripped)
        else:
            flush_code()
            if stripped:
                parts.append(stripped)

    flush_code()
    return "\n\n".join(parts)


def _format_markdown(results: list[dict]) -> str:
    """Format check results as markdown for Cursor chat rendering."""
    passed = sum(1 for r in results if r["ok"])
    failed = sum(1 for r in results if not r["ok"] and not r.get("optional"))
    warned = sum(1 for r in results if not r["ok"] and r.get("optional"))

    lines: list[str] = []

    if failed == 0 and warned == 0:
        lines.append("## \u2705 Conforma Prerequisites \u2014 All Passed")
        lines.append("")
        lines.append("| Check | Status |")
        lines.append("|-------|--------|")
        for r in results:
            detail = f" \u2014 {r['detail']}" if r.get("detail") else ""
            optional = " *(optional)*" if r.get("optional") else ""
            lines.append(f"| {r['name']}{optional} | \u2705 Pass{detail} |")
    else:
        summary_parts = []
        if passed:
            summary_parts.append(f"{passed} passed")
        if failed:
            summary_parts.append(f"{failed} failed")
        if warned:
            summary_parts.append(f"{warned} warned")
        lines.append(f"## Conforma Prerequisites \u2014 {', '.join(summary_parts)}")
        lines.append("")

        for r in results:
            is_optional = r.get("optional", False)
            lines.append("---")
            lines.append("")

            if r["ok"]:
                detail = f" \u2014 {r['detail']}" if r.get("detail") else ""
                optional = " *(optional)*" if is_optional else ""
                lines.append(f"### \u2705 {r['name']}{optional}{detail}")
                lines.append("")
            elif is_optional:
                lines.append(f"### \u26a0\ufe0f {r['name']} *(optional)*")
                lines.append("")
                lines.append(r["error"])
                lines.append("")
                if r.get("fix"):
                    lines.append(_format_fix_markdown(r["fix"]))
                    lines.append("")
            else:
                lines.append(f"### \u274c {r['name']}")
                lines.append("")
                lines.append(r["error"])
                lines.append("")
                if r.get("fix"):
                    lines.append(_format_fix_markdown(r["fix"]))
                    lines.append("")

        lines.append("---")
        lines.append("")
        footer_parts = []
        if passed:
            footer_parts.append(f"{passed} passed")
        if failed:
            footer_parts.append(f"{failed} failed")
        if warned:
            footer_parts.append(f"{warned} warned (optional)")
        status_msg = ", ".join(footer_parts)
        if failed:
            lines.append(f"*{status_msg}. Fix required checks before proceeding.*")
        else:
            lines.append(f"*{status_msg}. Ready to proceed.*")

    return "\n".join(lines)


def _format_text(results: list[dict], show_fix: bool) -> str:
    """Format check results as ASCII text for terminal display."""
    lines: list[str] = []
    passed = 0
    failed = 0
    warned = 0

    lines.append("=" * 60)
    lines.append("Conforma Workflow Prerequisites Check")
    lines.append("=" * 60)
    lines.append("")

    for r in results:
        is_optional = r.get("optional", False)
        if r["ok"]:
            passed += 1
            lines.append(f"  [\u2713] PASS  {r['name']}")
            if r.get("detail"):
                lines.append(f"          {r['detail']}")
        elif is_optional:
            warned += 1
            lines.append(f"  [!] WARN  {r['name']} (optional)")
            lines.append(f"          {r['error']}")
            if show_fix and r.get("fix"):
                for fix_line in r["fix"].split("\n"):
                    lines.append(f"          FIX: {fix_line}")
        else:
            failed += 1
            lines.append(f"  [\u2717] FAIL  {r['name']}")
            lines.append(f"          {r['error']}")
            if show_fix and r.get("fix"):
                for fix_line in r["fix"].split("\n"):
                    lines.append(f"          FIX: {fix_line}")
        lines.append("")

    lines.append("-" * 60)
    parts = [f"{passed} passed"]
    if failed:
        parts.append(f"{failed} failed")
    if warned:
        parts.append(f"{warned} warned (optional)")
    lines.append(f"  {', '.join(parts)}")
    lines.append("")

    if failed > 0:
        if not show_fix:
            lines.append("Re-run with --fix to see remediation steps.")
    elif warned > 0:
        lines.append("Optional checks have warnings \u2014 workflow can proceed without them.")
        if not show_fix:
            lines.append("Run with --fix to see setup instructions for optional services.")
        lines.append("")

    if failed == 0:
        lines.append("All required prerequisites satisfied. Ready to run conforma-analyze.")

    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify conforma-analyze prerequisites")
    parser.add_argument(
        "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="output_format",
        help="Output format: text (default, terminal), markdown (Cursor chat), json (programmatic)",
    )
    parser.add_argument("--json", action="store_true", help="(deprecated) Equivalent to --format json")
    parser.add_argument("--fix", action="store_true", help="Show fix instructions for failures")
    args = parser.parse_args()

    if args.json:
        args.output_format = "json"

    results = run_all_checks()
    required_ok = all(r["ok"] for r in results if not r.get("optional"))

    if args.output_format == "json":
        print(json.dumps(results, indent=2))
    elif args.output_format == "markdown":
        print(_format_markdown(results))
    else:
        print(_format_text(results, show_fix=args.fix))

    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
