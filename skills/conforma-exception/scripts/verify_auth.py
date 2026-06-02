#!/usr/bin/env python3
"""Pre-flight authentication check for conforma-exception.

Verifies that required CLI tools (acli, glab) are available (natively or via
container fallback) and authenticated before any Jira or GitLab operations.

All paths require both acli (Jira) and glab (GitLab) since all paths
create a RHOAIENG ticket and a GitLab MR.

Can be run standalone for debugging:
    python3 scripts/verify_auth.py --path A
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from cli_runner import (
    _ACLI_CONFIG_CANDIDATES,
    _DEFAULT_ACLI_IMAGE,
    _DEFAULT_GLAB_IMAGE,
    _container_runtime,
    _find_acli,
    _install_acli_local,
    _resolve_env,
    resolve_method,
    run_acli,
    run_glab,
    save_token,
)

GITLAB_HOST = "gitlab.cee.redhat.com"
GITLAB_PROJECT = "releng/konflux-release-data"


def _acli_auth_fix() -> str:
    """Build a method-aware fix command for acli authentication."""
    method = resolve_method("acli")
    if method == "native":
        return (
            "Generate a Jira API token at:\n"
            "  https://id.atlassian.com/manage-profile/security/api-tokens\n"
            "Then run (replace YOUR_TOKEN):\n"
            '  echo "YOUR_TOKEN" | acli jira auth login --site redhat.atlassian.net '
            "--email $USER@redhat.com --token"
        )
    runtime = _container_runtime()
    if not runtime:
        return "Install acli or a container runtime (docker/podman)"
    image = os.environ.get("ACLI_IMAGE", _DEFAULT_ACLI_IMAGE)
    config_dir = _ACLI_CONFIG_CANDIDATES[-1]
    return (
        "Generate a Jira API token at:\n"
        "  https://id.atlassian.com/manage-profile/security/api-tokens\n"
        "Then run this one-time login (replace YOUR_TOKEN):\n"
        f'  mkdir -p {config_dir} && echo "YOUR_TOKEN" | {runtime} run -i --rm '
        f'--network host --entrypoint "" '
        f"-v {config_dir}:/root/.config/acli "
        f"{image} acli jira auth login "
        f"--site redhat.atlassian.net --email $USER@redhat.com --token\n"
        "Verify with:\n"
        "  python3 scripts/verify_auth.py --path A"
    )


def _glab_auth_fix() -> str:
    """Build a method-aware fix command for glab authentication."""
    method = resolve_method("glab")
    token_url = f"https://{GITLAB_HOST}/-/user_settings/personal_access_tokens"
    if method == "native":
        return (
            f"1. Go to: {token_url}\n"
            f'  2. Name: "glab-cli", Expiration: 1 year, Scopes: api\n'
            f"  3. Click 'Create personal access token' and copy it\n"
            f"  4. Run (replace YOUR_TOKEN):\n"
            f'     glab auth login --hostname {GITLAB_HOST} --token "YOUR_TOKEN"'
        )
    runtime = _container_runtime()
    if not runtime:
        return "Install glab or a container runtime (docker/podman)"
    return (
        f"Generate a GitLab access token (api scope) at:\n"
        f"  {token_url}\n"
        f"Then set it and verify:\n"
        f'  export GITLAB_TOKEN="your-access-token"\n'
        f"  python3 scripts/verify_auth.py --path A\n"
        f"On success the token is saved automatically for future sessions."
    )


def check_acli_available() -> dict:
    """Check that acli is reachable, auto-installing to ~/.local/bin if needed."""
    if not _find_acli():
        try:
            _install_acli_local()
        except (RuntimeError, OSError):
            pass

    method = resolve_method("acli")
    acli_image = os.environ.get("ACLI_IMAGE", _DEFAULT_ACLI_IMAGE)
    if method == "unavailable":
        return {
            "check": "acli_available",
            "passed": False,
            "detail": "'acli' not found on PATH, auto-install failed, "
            "and no container runtime (docker/podman) available",
            "fix": "Check network connectivity and retry, or install acli manually: "
            "curl -LO https://acli.atlassian.com/linux/latest/acli_linux_amd64/acli "
            "&& chmod +x acli && mv acli ~/.local/bin/",
        }
    detail = f"acli via {method}"
    if method != "native":
        detail += f" (image: {acli_image})"
    return {
        "check": "acli_available",
        "passed": True,
        "detail": detail,
    }


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate long output to keep check results readable."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"... [{len(text) - max_len} chars truncated]"


def check_acli_auth() -> dict:
    """Check acli Jira authentication status."""
    try:
        result = run_acli(["jira", "auth", "status"], timeout=15)
        if result.returncode == 0:
            return {"check": "acli_auth", "passed": True, "detail": "authenticated"}
        return {
            "check": "acli_auth",
            "passed": False,
            "detail": _truncate(result.stderr.strip() or result.stdout.strip()),
            "fix": _acli_auth_fix(),
        }
    except subprocess.TimeoutExpired:
        return {
            "check": "acli_auth",
            "passed": False,
            "detail": "acli auth status timed out",
            "fix": f"Check network connectivity, then: {_acli_auth_fix()}",
        }
    except FileNotFoundError as exc:
        return {
            "check": "acli_auth",
            "passed": False,
            "detail": str(exc),
            "fix": "Install acli or a container runtime (docker/podman)",
        }


def check_glab_available() -> dict:
    """Check that glab is reachable (native binary or container)."""
    method = resolve_method("glab")
    glab_image = os.environ.get("GLAB_IMAGE", _DEFAULT_GLAB_IMAGE)
    if method == "unavailable":
        return {
            "check": "glab_available",
            "passed": False,
            "detail": "'glab' not found on PATH and no container runtime (docker/podman) available",
            "fix": f"Install glab (https://gitlab.com/gitlab-org/cli/-/releases), "
            f"or install docker/podman and pull {glab_image}",
        }
    detail = f"glab via {method}"
    if method != "native":
        detail += f" (image: {glab_image})"
    return {
        "check": "glab_available",
        "passed": True,
        "detail": detail,
    }


def check_glab_auth() -> dict:
    """Check glab authentication for gitlab.cee.redhat.com."""
    try:
        result = run_glab(
            ["auth", "status", "--hostname", GITLAB_HOST],
            timeout=15,
        )
        if result.returncode == 0:
            return {
                "check": "glab_auth",
                "passed": True,
                "detail": f"authenticated to {GITLAB_HOST}",
            }
        output = (result.stderr + result.stdout).strip()
        return {
            "check": "glab_auth",
            "passed": False,
            "detail": f"Not authenticated to {GITLAB_HOST}"
            if ("not logged in" in output.lower() or "no token" in output.lower())
            else output,
            "fix": _glab_auth_fix(),
        }
    except subprocess.TimeoutExpired:
        return {
            "check": "glab_auth",
            "passed": False,
            "detail": "glab auth status timed out",
            "fix": f"Check network connectivity, then: {_glab_auth_fix()}",
        }
    except FileNotFoundError as exc:
        return {
            "check": "glab_auth",
            "passed": False,
            "detail": str(exc),
            "fix": "Install glab or a container runtime (docker/podman)",
        }


def check_glab_push_access() -> dict:
    """Test push access to the konflux-release-data repo via glab API."""
    try:
        result = run_glab(
            [
                "api",
                "--hostname",
                GITLAB_HOST,
                f"projects/{GITLAB_PROJECT.replace('/', '%2F')}",
            ],
            timeout=15,
        )
        if result.returncode != 0:
            return {
                "check": "glab_push_access",
                "passed": False,
                "detail": f"Cannot access project {GITLAB_PROJECT}: {result.stderr.strip()}",
                "fix": f"Ensure you have Developer (30+) access to {GITLAB_HOST}/{GITLAB_PROJECT}",
            }
        try:
            data = json.loads(result.stdout)
            perms = data.get("permissions", {})
            proj = (perms.get("project_access") or {}).get("access_level", 0)
            grp = (perms.get("group_access") or {}).get("access_level", 0)
            access_level = max(proj, grp)
        except (json.JSONDecodeError, AttributeError):
            access_level = 0

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
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {
            "check": "glab_push_access",
            "passed": False,
            "detail": str(exc),
            "fix": f"Ensure glab is configured for {GITLAB_HOST}",
        }


def _persist_token_if_needed(env_var: str, check_name: str, checks: list[dict]) -> None:
    """If a token env var is set but not yet saved to file, persist it."""
    env_val = os.environ.get(env_var)
    if not env_val:
        return
    existing = _resolve_env(env_var)
    if existing == env_val:
        from cli_runner import _TOKEN_FILES

        token_file = _TOKEN_FILES.get(env_var)
        if token_file and token_file.is_file():
            return
    saved_path = save_token(env_var, env_val)
    checks.append(
        {
            "check": f"{check_name}_token_saved",
            "passed": True,
            "detail": f"{env_var} saved to {saved_path} (0600)",
        }
    )


def _extract_jira_email_from_acli() -> str | None:
    """Extract the Jira email from acli config (for REST API auth)."""
    try:
        import yaml

        config_path = _ACLI_CONFIG_CANDIDATES[-1].parent / "jira_config.yaml"
        if not config_path.is_file():
            for candidate in _ACLI_CONFIG_CANDIDATES:
                alt = candidate.parent / "jira_config.yaml"
                if alt.is_file():
                    config_path = alt
                    break
        if config_path.is_file():
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
            profiles = config.get("profiles", [])
            if profiles:
                return profiles[0].get("email")
    except Exception:
        pass
    return None


def _setup_jira_rest_api(checks: list[dict]) -> None:
    """Ensure JIRA_API_TOKEN and JIRA_EMAIL are available for REST API calls.

    Extracts email from acli config and persists tokens if set via env vars.
    """
    _persist_token_if_needed("JIRA_API_TOKEN", "jira", checks)

    email = _resolve_env("JIRA_EMAIL")
    if not email:
        email = _extract_jira_email_from_acli()
        if email:
            save_token("JIRA_EMAIL", email)
            checks.append(
                {
                    "check": "jira_email_detected",
                    "passed": True,
                    "detail": f"Jira email extracted from acli config: {email}",
                }
            )

    has_token = _resolve_env("JIRA_API_TOKEN") is not None
    checks.append(
        {
            "check": "jira_rest_api",
            "passed": True,
            "detail": "JIRA_API_TOKEN available (remote links enabled)"
            if has_token
            else "JIRA_API_TOKEN not set (remote links disabled, MR URLs in comments only)",
        }
    )


def run_checks(path: str) -> dict:
    """Run all relevant checks for the given path."""
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

    all_passed = all(c["passed"] for c in checks)
    return {
        "passed": all_passed,
        "path": path,
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-flight auth check for conforma-exception"
    )
    parser.add_argument(
        "--path",
        default="A",
        choices=["A", "B", "C"],
        help="Exception path (A=standard, B=FIPS, C=self-service)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_checks(args.path)
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
