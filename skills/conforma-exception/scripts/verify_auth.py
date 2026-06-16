#!/usr/bin/env python3
"""Pre-flight authentication check for conforma-exception.

Verifies that required CLI tools (acli, glab) are available (natively or via
container fallback) and authenticated before any Jira or GitLab operations.

All workflows require both acli (Jira) and glab (GitLab) since all workflows
create at least a RHOAIENG ticket and a GitLab MR.

Can be run standalone for debugging:
    python3 scripts/verify_auth.py
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import json
import os
import sys

import gitlab_ops
import jira_ops


GITLAB_HOST = os.environ.get("GITLAB_HOST", "")
GITLAB_PROJECT = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")


def _ensure_jira_env() -> None:
    """Ensure jira env vars are available (site_config.load() already handles this)."""
    pass


def _ensure_gitlab_env() -> None:
    """Ensure gitlab env vars are available (site_config.load() already handles this)."""
    pass


def _jira_auth_fix() -> str:
    """Build fix instructions for Jira authentication."""
    return (
        "Generate a Jira API token at:\n"
        "  https://id.atlassian.com/manage-profile/security/api-tokens\n"
        "Then add to .work/.env:\n"
        "  JIRA_API_TOKEN=your-token\n"
        "  JIRA_EMAIL=your-email@redhat.com"
    )


def _gitlab_auth_fix() -> str:
    """Build fix instructions for GitLab authentication."""
    token_url = f"https://{GITLAB_HOST}/-/user_settings/personal_access_tokens"
    return (
        f"Generate a GitLab access token (api scope) at:\n"
        f"  {token_url}\n"
        f"Then add to .work/.env:\n"
        f"  GITLAB_TOKEN=your-access-token"
    )


# Legacy aliases for compatibility
_acli_auth_fix = _jira_auth_fix
_glab_auth_fix = _gitlab_auth_fix


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate long output to keep check results readable."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"... [{len(text) - max_len} chars truncated]"


def check_acli_available() -> dict:
    """Check Jira library availability (replaces acli check)."""
    return {
        "check": "acli_available",
        "passed": True,
        "detail": "jira_ops (python-jira library)",
    }


def check_acli_auth() -> dict:
    """Check Jira authentication via python-jira library."""
    _ensure_jira_env()
    auth_result = jira_ops.verify_auth()
    if auth_result["ok"]:
        return {"check": "acli_auth", "passed": True, "detail": f"authenticated as {auth_result['user']}"}
    return {
        "check": "acli_auth",
        "passed": False,
        "detail": auth_result.get("error", "Authentication failed"),
        "fix": _jira_auth_fix(),
    }


def check_glab_available() -> dict:
    """Check GitLab library availability (replaces glab check)."""
    return {
        "check": "glab_available",
        "passed": True,
        "detail": "gitlab_ops (python-gitlab library)",
    }


def check_glab_auth() -> dict:
    """Check GitLab authentication via python-gitlab library."""
    _ensure_gitlab_env()
    token = gitlab_ops.discover_token(GITLAB_HOST)
    if not token:
        return {
            "check": "glab_auth",
            "passed": False,
            "detail": f"No GitLab token found for {GITLAB_HOST}",
            "fix": _gitlab_auth_fix(),
        }
    try:
        gl = gitlab_ops.get_client(instance_url=GITLAB_HOST)
        gl.auth()
        return {
            "check": "glab_auth",
            "passed": True,
            "detail": f"authenticated to {GITLAB_HOST}",
        }
    except Exception as exc:
        return {
            "check": "glab_auth",
            "passed": False,
            "detail": str(exc),
            "fix": _gitlab_auth_fix(),
        }


def check_glab_push_access() -> dict:
    """Test push access to the konflux-release-data repo via python-gitlab."""
    _ensure_gitlab_env()
    try:
        gl = gitlab_ops.get_client(instance_url=GITLAB_HOST)
        project = gl.projects.get(GITLAB_PROJECT)

        perms = project.attributes.get("permissions", {})
        proj_access = (perms.get("project_access") or {}).get("access_level", 0)
        grp_access = (perms.get("group_access") or {}).get("access_level", 0)
        access_level = max(proj_access, grp_access)

        if access_level >= 30:
            return {
                "check": "glab_push_access",
                "passed": True,
                "detail": f"Access level {access_level} on {GITLAB_PROJECT}",
            }
        return {
            "check": "glab_push_access",
            "passed": True,
            "detail": f"Access level {access_level} < 30 (Developer) on {GITLAB_PROJECT}. "
            f"Will use fork-based MR as fallback.",
            "warning": True,
        }
    except Exception as exc:
        return {
            "check": "glab_push_access",
            "passed": False,
            "detail": str(exc),
            "fix": f"Ensure GITLAB_TOKEN has access to {GITLAB_HOST}/{GITLAB_PROJECT}",
        }


def _persist_token_if_needed(env_var: str, check_name: str, checks: list[dict]) -> None:
    """No-op: tokens are managed via .work/.env and site_config.load()."""
    pass


def _setup_jira_rest_api(checks: list[dict]) -> None:
    """Verify JIRA_API_TOKEN and JIRA_EMAIL are available."""
    has_token = os.environ.get("JIRA_API_TOKEN") is not None
    has_email = os.environ.get("JIRA_EMAIL") is not None
    checks.append(
        {
            "check": "jira_rest_api",
            "passed": has_token and has_email,
            "detail": "JIRA_API_TOKEN and JIRA_EMAIL available"
            if (has_token and has_email)
            else "JIRA_API_TOKEN or JIRA_EMAIL not set in .work/.env",
            "fix": _jira_auth_fix() if not (has_token and has_email) else None,
        }
    )


def _check_jira_library_auth() -> dict:
    """Cross-check Jira auth using the jira Python library (shared jira_ops)."""
    _ensure_jira_env()
    try:
        result = jira_ops.verify_auth()
        if result.get("ok"):
            return {
                "check": "jira_library_auth",
                "passed": True,
                "detail": f"python-jira authenticated as {result.get('user', 'unknown')}",
            }
        return {
            "check": "jira_library_auth",
            "passed": False,
            "detail": result.get("error", "unknown error"),
        }
    except Exception as exc:
        return {
            "check": "jira_library_auth",
            "passed": False,
            "detail": str(exc),
        }


def _check_gitlab_library_auth() -> dict:
    """Cross-check GitLab auth using python-gitlab (shared gitlab_ops)."""
    _ensure_gitlab_env()
    try:
        result = gitlab_ops.verify_auth(instance_url=GITLAB_HOST)
        if result.get("ok"):
            return {
                "check": "gitlab_library_auth",
                "passed": True,
                "detail": f"python-gitlab authenticated as {result.get('user', 'unknown')} on {GITLAB_HOST}",
            }
        return {
            "check": "gitlab_library_auth",
            "passed": False,
            "detail": result.get("error", "unknown error"),
        }
    except Exception as exc:
        return {
            "check": "gitlab_library_auth",
            "passed": False,
            "detail": str(exc),
        }


def run_checks() -> dict:
    """Run all auth checks (acli for Jira, glab for GitLab, library cross-checks)."""
    checks: list[dict] = []

    checks.append(check_acli_available())
    if checks[-1]["passed"]:
        checks.append(check_acli_auth())
        _setup_jira_rest_api(checks)

    checks.append(check_glab_available())
    if checks[-1]["passed"]:
        checks.append(check_glab_auth())
        if checks[-1]["passed"]:
            _persist_token_if_needed("GITLAB_TOKEN", "glab", checks)
            checks.append(check_glab_push_access())

    checks.append(_check_jira_library_auth())
    checks.append(_check_gitlab_library_auth())

    all_passed = all(c["passed"] for c in checks)
    return {
        "passed": all_passed,
        "checks": checks,
    }


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
