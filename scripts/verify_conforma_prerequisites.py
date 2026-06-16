#!/usr/bin/env python3
"""Verify all prerequisites for running the conforma-analyze workflow.

Checks (in order):
  1. Python dependencies (requests, yaml, gitlab, jira)
  2. Site configuration (.work/.env loaded, site-config.yaml present)
  3. GitHub authentication (private conforma-reporter access)
  4. GitLab authentication (VPN + token for konflux-release-data)
  5. Jira authentication (API token + email for coverage search)
  6. Slack authentication (slackdump binary + session) — OPTIONAL

Slack is optional because it requires more complex setup (manual token/cookie
extraction from browser DevTools) compared to other services which use simple
API tokens. The workflow can proceed without Slack — the coverage table will
omit Slack thread references.

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
import sys
from pathlib import Path

_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import site_config

site_config.load()

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
    return {"ok": True, "name": "python_deps", "error": None, "fix": None}


def _check_site_config() -> dict:
    """Check that site configuration is loaded with required fields."""
    required_vars = ["GITLAB_HOST", "KRD_CLUSTER_DOMAIN"]
    missing = [v for v in required_vars if not os.environ.get(v)]

    if missing:
        return {
            "ok": False,
            "name": "site_config",
            "error": f"Missing site-config vars: {', '.join(missing)}",
            "fix": (
                "Copy and fill: cp .work/site-config.example.yaml "
                "~/.config/aiops-infra/site-config.yaml\n"
                "  Or run: python3 scripts/site_config.py --refresh"
            ),
        }
    return {"ok": True, "name": "site_config", "error": None, "fix": None}


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
    return {"ok": True, "name": "dotenv", "error": None, "fix": None}


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
        "fix": "Set GITHUB_TOKEN in .work/.env (scope: repo for private repos)",
    }


def _check_gitlab_auth() -> dict:
    """Check GitLab authentication."""
    import gitlab_ops

    host = os.environ.get("GITLAB_HOST", "")
    if not host:
        return {
            "ok": False,
            "name": "gitlab",
            "error": "GITLAB_HOST not set (site-config missing)",
            "fix": "Fix site-config first",
        }

    result = gitlab_ops.verify_auth(instance_url=f"https://{host}")
    if result.get("ok"):
        return {
            "ok": True,
            "name": "gitlab",
            "error": None,
            "fix": None,
            "detail": f"Authenticated as: {result.get('user')}",
        }
    return {
        "ok": False,
        "name": "gitlab",
        "error": result.get("error", "Unknown error"),
        "fix": (
            "Ensure VPN is connected, then set GITLAB_TOKEN in .work/.env\n"
            "  (scope: api, read_repository, write_repository)"
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
            "Set JIRA_API_TOKEN in .work/.env\n"
            "  (JIRA_EMAIL auto-derives on first successful auth)"
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
            "error": "slackdump not installed",
            "fix": (
                "Run: bash scripts/install_slackdump.sh\n"
                "  Then authenticate — see: skills/slack-auth/SKILL.md (Method A: manual token/cookie)"
            ),
        }
    return {
        "ok": False,
        "name": "slack",
        "optional": True,
        "error": error,
        "fix": (
            "Authenticate slackdump — see: skills/slack-auth/SKILL.md (Method A: manual token/cookie)\n"
            "  Requires extracting token+cookie from browser DevTools (more involved than other services)"
        ),
    }


def run_all_checks() -> list[dict]:
    """Run all prerequisite checks and return results."""
    checks = [
        _check_python_deps,
        _check_dotenv,
        _check_site_config,
        _check_github_auth,
        _check_gitlab_auth,
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


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify conforma-analyze prerequisites")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--fix", action="store_true", help="Show fix instructions for failures")
    args = parser.parse_args()

    results = run_all_checks()

    if args.json:
        print(json.dumps(results, indent=2))
        required_ok = all(r["ok"] for r in results if not r.get("optional"))
        return 0 if required_ok else 1

    passed = 0
    failed = 0
    warned = 0
    print("=" * 60)
    print("Conforma Workflow Prerequisites Check")
    print("=" * 60)
    print()

    for r in results:
        is_optional = r.get("optional", False)
        if r["ok"]:
            passed += 1
            icon = "\u2713"
            status = "PASS"
            print(f"  [{icon}] {status}  {r['name']}")
            if r.get("detail"):
                print(f"          {r['detail']}")
        elif is_optional:
            warned += 1
            icon = "!"
            status = "WARN"
            print(f"  [{icon}] {status}  {r['name']} (optional)")
            print(f"          {r['error']}")
            if args.fix and r.get("fix"):
                for line in r["fix"].split("\n"):
                    print(f"          FIX: {line}")
        else:
            failed += 1
            icon = "\u2717"
            status = "FAIL"
            print(f"  [{icon}] {status}  {r['name']}")
            print(f"          {r['error']}")
            if args.fix and r.get("fix"):
                for line in r["fix"].split("\n"):
                    print(f"          FIX: {line}")
        print()

    print("-" * 60)
    parts = [f"{passed} passed"]
    if failed:
        parts.append(f"{failed} failed")
    if warned:
        parts.append(f"{warned} warned (optional)")
    print(f"  {', '.join(parts)}")
    print()

    if failed > 0:
        print("Re-run with --fix to see remediation steps.")
        return 1

    if warned > 0:
        print("Optional checks have warnings — workflow can proceed without them.")
        print("Run with --fix to see setup instructions for optional services.")
        print()

    print("All required prerequisites satisfied. Ready to run conforma-analyze.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
