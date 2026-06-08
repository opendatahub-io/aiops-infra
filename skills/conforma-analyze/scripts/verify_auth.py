#!/usr/bin/env python3
"""Pre-flight authentication check for conforma-analyze.

Verifies that gh CLI is available and authenticated, and that the user has
read access to the private red-hat-data-services/conforma-reporter repository.

Usage:
    python3 scripts/verify_auth.py
"""

from __future__ import annotations

import json
import subprocess
import sys


CONFORMA_REPORTER_REPO = "red-hat-data-services/conforma-reporter"


def check_gh_available() -> dict:
    """Check that gh CLI is on PATH."""
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip().splitlines()[0]
            return {"check": "gh_available", "passed": True, "detail": version}
        return {
            "check": "gh_available",
            "passed": False,
            "detail": result.stderr.strip(),
            "fix": "Install gh CLI: https://cli.github.com/",
        }
    except FileNotFoundError:
        return {
            "check": "gh_available",
            "passed": False,
            "detail": "gh not found on PATH",
            "fix": "Install gh CLI: https://cli.github.com/",
        }


def check_gh_auth() -> dict:
    """Check that gh CLI is authenticated."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return {"check": "gh_auth", "passed": True, "detail": "authenticated"}
        output = (result.stderr + result.stdout).strip()
        return {
            "check": "gh_auth",
            "passed": False,
            "detail": output[:300],
            "fix": "Run: gh auth login",
        }
    except subprocess.TimeoutExpired:
        return {
            "check": "gh_auth",
            "passed": False,
            "detail": "gh auth status timed out",
            "fix": "Check network connectivity, then: gh auth login",
        }


def check_repo_access() -> dict:
    """Check read access to the conforma-reporter repository."""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{CONFORMA_REPORTER_REPO}", "--jq", ".full_name"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and CONFORMA_REPORTER_REPO in result.stdout:
            return {
                "check": "repo_access",
                "passed": True,
                "detail": f"Read access to {CONFORMA_REPORTER_REPO} confirmed",
            }
        return {
            "check": "repo_access",
            "passed": False,
            "detail": f"Cannot access {CONFORMA_REPORTER_REPO}: "
            + (result.stderr.strip() or result.stdout.strip())[:200],
            "fix": (
                f"Ensure your GITHUB_TOKEN has read access to {CONFORMA_REPORTER_REPO}. "
                f"This is a private repository. Ask your team lead for access if needed."
            ),
        }
    except subprocess.TimeoutExpired:
        return {
            "check": "repo_access",
            "passed": False,
            "detail": "API request timed out",
            "fix": "Check network connectivity and VPN status.",
        }


def run_checks() -> dict:
    """Run all auth checks."""
    checks: list[dict] = []

    checks.append(check_gh_available())
    if not checks[-1]["passed"]:
        return {"passed": False, "checks": checks}

    checks.append(check_gh_auth())
    if not checks[-1]["passed"]:
        return {"passed": False, "checks": checks}

    checks.append(check_repo_access())

    all_passed = all(c["passed"] for c in checks)
    return {"passed": all_passed, "checks": checks}


def main() -> int:
    result = run_checks()
    print(json.dumps(result, indent=2))

    if not result["passed"]:
        print("\n--- Setup instructions ---", file=sys.stderr)
        for check in result["checks"]:
            if not check["passed"]:
                print(f"  FAIL: {check['check']}: {check['detail']}", file=sys.stderr)
                if "fix" in check:
                    print(f"        Fix: {check['fix']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
