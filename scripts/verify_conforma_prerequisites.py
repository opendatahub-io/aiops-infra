#!/usr/bin/env python3
"""Verify all prerequisites for running the conforma-analyze workflow.

Checks (in order):
  1. Python dependencies (requests, yaml, gitlab, jira)
  2. ~/.conforma/.env file (secrets: tokens, credentials)
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
from pathlib import Path


import konflux_environment  # noqa: E402

konflux_environment.load()


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
            "fix": "uv sync\n(or: pip install -e .)",
        }
    return {"ok": True, "name": "python_deps", "error": None, "fix": None, "detail": "All installed"}


def _check_konflux() -> dict:
    """Check that Konflux tenant is configured and cluster is reachable.

    Primary path: user provides KONFLUX_TENANT in ~/.conforma/.env alongside GITLAB_HOST,
    then KONFLUX_CLUSTER_DOMAIN is auto-discovered by konflux_tenant_env_discovery.py.

    Auto-discovery depends on GitLab auth. If GitLab is not configured, this
    check reports the dependency rather than a generic "discovery failed".

    After verifying config, tests actual connectivity via oc/kubectl whoami.
    """
    # The module-level load() may have skipped discovery because the connectivity
    # state file didn't exist yet. _check_gitlab_auth() writes it on success, so
    # retry discovery here now that the state file exists.
    if not os.environ.get("KONFLUX_CLUSTER_DOMAIN") and os.environ.get("KONFLUX_TENANT"):
        konflux_environment._loaded = False
        konflux_environment.load()

    has_tenant = bool(os.environ.get("KONFLUX_TENANT"))
    has_cluster_domain = bool(os.environ.get("KONFLUX_CLUSTER_DOMAIN"))

    if not has_tenant:
        return {
            "ok": False,
            "name": "konflux",
            "error": "KONFLUX_TENANT not set",
            "fix": (
                "Add to ~/.conforma/.env:\n"
                "  KONFLUX_TENANT=your-konflux-tenant-name\n"
                "Then re-run — KONFLUX_CLUSTER_DOMAIN will be auto-discovered."
            ),
        }

    # KONFLUX_TENANT is set but CLUSTER_DOMAIN is missing — discovery didn't work.
    # Distinguish "blocked by gitlab" from a discovery-specific failure.
    if not has_cluster_domain:
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
            # Discovery succeeded — derive secondary vars so everything is consistent.
            konflux_environment.load()
            cluster_domain = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
            if not cluster_domain:
                return {
                    "ok": False,
                    "name": "konflux",
                    "error": "Discovery succeeded but KONFLUX_CLUSTER_DOMAIN is still unset",
                    "fix": ("This is unexpected. Try manually setting:\n  KONFLUX_CLUSTER_DOMAIN=your-cluster-domain"),
                }
        except Exception as exc:
            error_msg = str(exc)
            # Provide actionable fix based on the specific error.
            if "multiple clusters" in error_msg.lower():
                return {
                    "ok": False,
                    "name": "konflux",
                    "error": error_msg,
                    "fix": ("Add to ~/.conforma/.env:\n  PREFERRED_KONFLUX_CLUSTER=your-cluster-id"),
                }
            return {
                "ok": False,
                "name": "konflux",
                "error": f"Auto-discovery failed: {error_msg}",
                "fix": (
                    "Retry discovery:\n"
                    "  python3 scripts/konflux_tenant_env_discovery.py --tenant $KONFLUX_TENANT --human\n"
                    "If discovery cannot work in your environment, add manually to ~/.conforma/.env:\n"
                    "  KONFLUX_CLUSTER_DOMAIN=your-cluster-domain"
                ),
            }

    # Config looks good — now test actual connectivity via DNS + HTTPS probe
    cluster_domain = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
    cluster_id = cluster_domain.split(".")[0] if cluster_domain else ""
    api_host = f"api.{cluster_domain}.openshiftapps.com"

    dns_ok, https_ok, probe_error = _probe_konflux_cluster(api_host)

    if not dns_ok:
        return {
            "ok": False,
            "name": "konflux",
            "error": probe_error,
            "fix": (f"VPN CONNECTION REQUIRED: Cannot resolve {api_host}\n**Connect to Red Hat VPN, then retry.**"),
        }

    if not https_ok:
        return {
            "ok": False,
            "name": "konflux",
            "error": probe_error,
            "fix": (
                f"Konflux cluster {cluster_id} DNS resolves but HTTPS connection failed.\n"
                f"**Connect to Red Hat VPN, then retry.**"
            ),
        }

    # Network is reachable — try oc/kubectl auth if available
    conn_result = konflux_environment.ConnectivityResult()
    konflux_environment._check_konflux_connectivity(conn_result)

    if conn_result.konflux_reachable is True:
        return {
            "ok": True,
            "name": "konflux",
            "error": None,
            "fix": None,
            "detail": f"Cluster: {cluster_id} (authenticated)",
        }

    if conn_result.konflux_reachable is False:
        error_detail = conn_result.error_details.get("konflux", "Cluster not reachable")
        return {
            "ok": False,
            "name": "konflux",
            "error": error_detail,
            "fix": (
                f"Cluster {cluster_id} is reachable but not authenticated.\n"
                f"Authenticate with:\n"
                f"  oc login --server=https://{api_host}:6443"
            ),
        }

    # oc/kubectl not available or EXTERNAL_API not set — DNS+HTTPS passed, that's enough
    return {
        "ok": True,
        "name": "konflux",
        "error": None,
        "fix": None,
        "detail": f"Cluster: {cluster_id} (reachable)",
    }


def _probe_konflux_cluster(api_host: str) -> tuple[bool, bool, str | None]:
    """DNS + HTTPS probe for a Konflux cluster API host.

    Returns (dns_ok, https_ok, error_message).
    """
    import socket

    try:
        socket.getaddrinfo(api_host, 6443)
    except (socket.gaierror, OSError) as exc:
        return False, False, f"Cannot resolve {api_host}: {exc}"

    import ssl
    import urllib.error
    import urllib.request

    url = f"https://{api_host}:6443/healthz"
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            _ = resp.status
        return True, True, None
    except urllib.error.HTTPError:
        # Any HTTP response (401, 403, etc.) means HTTPS works
        return True, True, None
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            # SSL cert issue but connection worked
            return True, True, None
        return True, False, f"Cannot connect to https://{api_host}:6443: {exc}"
    except (OSError, ConnectionError) as exc:
        return True, False, f"Cannot connect to https://{api_host}:6443: {exc}"


def _check_dotenv() -> dict:
    """Check that ~/.conforma/.env exists."""
    dotenv_path = konflux_environment._resolve_dotenv_path()
    if not dotenv_path.is_file():
        return {
            "ok": False,
            "name": "dotenv",
            "error": "~/.conforma/.env not found",
            "fix": (
                "Create ~/.conforma/.env with your credentials:\n"
                "  mkdir -p ~/.conforma\n"
                "  touch ~/.conforma/.env\n"
                "(then add tokens)"
            ),
        }
    return {"ok": True, "name": "dotenv", "error": None, "fix": None, "detail": str(dotenv_path)}


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
            " and add to ~/.conforma/.env:\n"
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
            "fix": ("Add to ~/.conforma/.env:\n  GITLAB_HOST=your-gitlab-host"),
        }

    import gitlab_ops

    result = gitlab_ops.verify_auth(instance_url=f"https://{host}")
    if result.get("ok"):
        # Write connectivity state file so subsequent processes (e.g.
        # resolve_release_context.py) see connectivity_confirmed() → True
        # and can auto-discover KONFLUX_CLUSTER_DOMAIN via tenant discovery.
        try:
            konflux_environment.check_connectivity()
        except Exception:
            pass  # best-effort; auth check already passed
        return {
            "ok": True,
            "name": "gitlab",
            "error": None,
            "fix": None,
            "detail": f"Authenticated as: {result.get('user')}",
        }

    error_str = result.get("error", "Unknown error")
    token_url = f"https://{host}/-/user_settings/personal_access_tokens"

    # Detect VPN/DNS/connectivity failures and prioritize them in the fix message
    is_vpn_issue = any(
        indicator in error_str
        for indicator in [
            "Failed to resolve",
            "Name or service not known",
            "NameResolutionError",
            "Max retries exceeded",
            "Connection refused",
            "Network is unreachable",
        ]
    )

    if is_vpn_issue:
        return {
            "ok": False,
            "name": "gitlab",
            "error": error_str,
            "fix": (
                f"VPN CONNECTION REQUIRED: Cannot resolve {host}\n"
                f"**Connect to Red Hat VPN, then retry.**\n"
                f"\n"
                f"If VPN is connected and the error persists, ensure you have a Personal Access Token ({token_url})"
                f" with scopes: api, read_repository, write_repository in ~/.conforma/.env:\n"
                f"  GITLAB_TOKEN=glpat-your_token_here"
            ),
        }

    # Check if token exists
    has_token = bool(os.environ.get("GITLAB_TOKEN"))
    if not has_token:
        return {
            "ok": False,
            "name": "gitlab",
            "error": error_str,
            "fix": (
                f"No GitLab token found in ~/.conforma/.env\n"
                f"Create a Personal Access Token ({token_url})"
                f" with scopes: api, read_repository, write_repository and add to ~/.conforma/.env:\n"
                f"  GITLAB_TOKEN=glpat-your_token_here"
            ),
        }

    # Token exists but auth failed → invalid/expired
    return {
        "ok": False,
        "name": "gitlab",
        "error": error_str,
        "fix": (
            f"GitLab authentication failed (token exists but is invalid or expired)\n"
            f"Regenerate your Personal Access Token ({token_url})"
            f" with scopes: api, read_repository, write_repository and update ~/.conforma/.env:\n"
            f"  GITLAB_TOKEN=glpat-your_new_token_here"
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

    error_str = result.get("error", "Unknown error")
    has_token = bool(os.environ.get("JIRA_API_TOKEN"))
    has_email = bool(os.environ.get("JIRA_EMAIL"))

    # Detect VPN/connectivity failures (Jira is VPN-gated like GitLab)
    is_vpn_issue = any(
        indicator in error_str
        for indicator in [
            "Failed to resolve",
            "Name or service not known",
            "NameResolutionError",
            "Max retries exceeded",
            "Connection refused",
            "Network is unreachable",
        ]
    )

    if is_vpn_issue:
        return {
            "ok": False,
            "name": "jira",
            "error": error_str,
            "fix": (
                "VPN CONNECTION REQUIRED: Cannot reach Jira (redhat.atlassian.net)\n"
                "**Connect to Red Hat VPN, then retry.**\n"
                "\n"
                "If VPN is connected and the error persists, ensure you have Jira credentials in ~/.conforma/.env:\n"
                "  JIRA_API_TOKEN=your_jira_api_token\n"
                "  JIRA_EMAIL=you@redhat.com"
            ),
        }

    # Distinguish between missing credentials vs invalid credentials
    if not has_token and not has_email:
        return {
            "ok": False,
            "name": "jira",
            "error": error_str,
            "fix": (
                "No Jira credentials found in ~/.conforma/.env\n"
                "Create an API token (https://id.atlassian.com/manage-profile/security/api-tokens)"
                " and add to ~/.conforma/.env:\n"
                "  JIRA_API_TOKEN=your_jira_api_token\n"
                "  JIRA_EMAIL=you@redhat.com"
            ),
        }

    # Token exists but auth failed → invalid/expired
    return {
        "ok": False,
        "name": "jira",
        "error": error_str,
        "fix": (
            "Jira authentication failed (token exists but is invalid or expired)\n"
            "Regenerate your API token (https://id.atlassian.com/manage-profile/security/api-tokens)"
            " and update ~/.conforma/.env:\n"
            "  JIRA_API_TOKEN=your_new_jira_api_token"
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

    slack_fix_msg = (
        "Without Slack the Conforma Report is produced as normal but "
        "it will be missing links to Slack conversations that might be "
        "related to the Conforma Violations."
    )

    error = result.get("error", "Unknown error")
    if "not found" in error.lower() or "not installed" in error.lower():
        return {
            "ok": False,
            "name": "slack",
            "optional": True,
            "error": "slackdump is not installed.",
            "fix": slack_fix_msg,
        }
    return {
        "ok": False,
        "name": "slack",
        "optional": True,
        "error": "No Slack auth credentials found.",
        "fix": slack_fix_msg,
    }


_QUAY_AUTH_CONFIG_PATHS = [
    Path(os.environ.get("DOCKER_CONFIG", "")) / "config.json",
    Path.home() / ".docker" / "config.json",
    Path(os.environ.get("XDG_RUNTIME_DIR", "")) / "containers" / "auth.json",
    Path.home() / ".config" / "containers" / "auth.json",
]

_QUAY_TEST_URL = "https://quay.io/v2/rhoai/odh-dashboard-rhel9/tags/list"


def _find_quay_auth() -> tuple[str | None, Path | None]:
    """Find quay.io credentials from standard container auth config files.

    Returns (base64_auth_value, config_path) or (None, None).
    """
    for config_path in _QUAY_AUTH_CONFIG_PATHS:
        if not config_path.is_file():
            continue
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            auths = data.get("auths", {})
            for key in ("quay.io", "https://quay.io", "quay.io/rhoai"):
                entry = auths.get(key, {})
                auth_val = entry.get("auth", "")
                if auth_val:
                    return auth_val, config_path
        except (json.JSONDecodeError, OSError):
            continue
    return None, None


def _check_quay_auth() -> dict:
    """Check quay.io registry authentication.

    EC validate needs registry credentials to pull private container images.
    Without auth, all components get builtin.image.accessible and no policy
    rules are evaluated.
    """
    import requests

    auth_val, config_path = _find_quay_auth()

    if auth_val is None:
        searched = [str(p) for p in _QUAY_AUTH_CONFIG_PATHS if p.parent.exists()]
        return {
            "ok": False,
            "name": "quay",
            "error": (
                "Container image violations cannot be confirmed against the "
                "actual container images in the registry — quay.io "
                "authentication is required"
            ),
            "fix": (
                "podman login quay.io\n"
                "(Use your quay.io credentials. This stores auth in "
                "~/.config/containers/auth.json which EC reads automatically.)\n"
                f"Searched: {', '.join(searched) or '(no standard paths found)'}"
            ),
        }

    token_url = "https://quay.io/v2/auth?service=quay.io&scope=repository:rhoai/odh-dashboard-rhel9:pull"
    try:
        token_resp = requests.get(
            token_url,
            headers={"Authorization": f"Basic {auth_val}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "name": "quay",
            "error": f"quay.io connectivity check failed: {exc}",
            "fix": (
                "Ensure network access to quay.io is available.\n"
                "If behind a proxy, configure HTTPS_PROXY in ~/.conforma/.env"
            ),
        }

    if token_resp.status_code == 401:
        return {
            "ok": False,
            "name": "quay",
            "error": (
                "Container image violations cannot be confirmed against the "
                "actual container images in the registry — quay.io "
                "credentials are invalid or expired"
            ),
            "fix": (
                f"podman login quay.io\n(Re-authenticate with valid credentials. Current auth config: {config_path})"
            ),
        }

    if token_resp.status_code != 200:
        return {
            "ok": False,
            "name": "quay",
            "error": (
                "Container image violations cannot be confirmed against the "
                f"actual container images in the registry — quay.io auth "
                f"returned HTTP {token_resp.status_code}"
            ),
            "fix": (f"podman login quay.io\nCurrent auth config: {config_path}"),
        }

    token_data = token_resp.json()
    bearer_token = token_data.get("token", "")
    if not bearer_token:
        return {
            "ok": False,
            "name": "quay",
            "error": (
                "Container image violations cannot be confirmed against the "
                "actual container images in the registry — quay.io auth "
                "returned no token"
            ),
            "fix": (f"podman login quay.io\nCurrent auth config: {config_path}"),
        }

    try:
        resp = requests.head(
            _QUAY_TEST_URL,
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "name": "quay",
            "error": f"quay.io connectivity check failed: {exc}",
            "fix": (
                "Ensure network access to quay.io is available.\n"
                "If behind a proxy, configure HTTPS_PROXY in ~/.conforma/.env"
            ),
        }

    if resp.status_code == 403:
        return {
            "ok": False,
            "name": "quay",
            "error": (
                "Container image violations cannot be confirmed against the "
                "actual container images in the registry — quay.io "
                "credentials lack access to RHOAI images"
            ),
            "fix": (
                "Ensure your quay.io account has read access to the "
                "quay.io/rhoai organization.\n"
                "podman login quay.io\n"
                f"Current auth config: {config_path}"
            ),
        }

    if resp.status_code not in (200, 301, 302):
        return {
            "ok": False,
            "name": "quay",
            "error": (
                "Container image violations cannot be confirmed against the "
                f"actual container images in the registry — quay.io "
                f"returned HTTP {resp.status_code}"
            ),
            "fix": (f"podman login quay.io\nCurrent auth config: {config_path}"),
        }

    return {
        "ok": True,
        "name": "quay",
        "error": None,
        "fix": None,
        "detail": f"Authenticated (config: {config_path})",
    }


def run_all_checks() -> list[dict]:
    """Run all prerequisite checks and return results."""
    checks = [
        _check_python_deps,
        _check_dotenv,
        _check_gitlab_auth,
        _check_konflux,
        _check_github_auth,
        _check_quay_auth,
        _check_jira_auth,
        _check_slack_auth,
    ]
    results = []
    for check_fn in checks:
        try:
            results.append(check_fn())
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "name": check_fn.__name__.replace("_check_", ""),
                    "error": f"Check raised exception: {exc}",
                    "fix": None,
                }
            )
    return results


def _is_code_line(line: str) -> bool:
    """Heuristic: line looks like a KEY=value assignment or shell command."""
    stripped = line.strip()
    if re.match(r"^[A-Z_]+=", stripped):
        return True
    if re.match(r"^(echo|python3|bash|cp |pip |uv |podman |docker )", stripped):
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

    slack_result = next(
        (r for r in results if r.get("name") == "slack"),
        None,
    )
    slack_available = slack_result["ok"] if slack_result else False
    try:
        import conforma_context_ops

        run_dir = conforma_context_ops.discover_run_dir()
        conforma_context_ops.update_step(
            run_dir,
            "prerequisites",
            "completed",
            slack_available=slack_available,
        )
    except (FileNotFoundError, ImportError):
        pass

    if args.output_format == "json":
        slack_warn = next(
            (r for r in results if r.get("name") == "slack" and r.get("optional") and not r.get("ok")),
            None,
        )
        output: dict = {
            "display": _format_markdown(results),
            "checks": results,
            "passed": required_ok,
        }
        if slack_warn:
            error_detail = slack_warn.get("error", "no credentials found")
            output["user_question"] = {
                "question_text": (
                    f"Slack is not configured ({error_detail}). "
                    "Without Slack, the coverage report will not include links to related Slack threads. "
                    "Proceed without Slack?"
                ),
                "question_options": ["Yes, proceed without Slack", "No, set up Slack first"],
            }
        print(json.dumps(output, indent=2))
    elif args.output_format == "markdown":
        print(_format_markdown(results))
    else:
        print(_format_text(results, show_fix=args.fix))

    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
