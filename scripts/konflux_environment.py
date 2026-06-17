"""Konflux environment loader for aiops-infra (dual-mode: CLI + importable).

Populates environment variables from ``.work/.env``, derives secondary vars
from KONFLUX_CLUSTER_DOMAIN, and integrates with tenant auto-discovery.

Sources (first value wins, existing env vars are never overwritten):
  1. Environment variables already set
  2. .work/.env file (secrets, infrastructure config)
  3. Auto-discovery via konflux_tenant_env_discovery (when KONFLUX_TENANT is set)

Usage as library:
    import konflux_environment
    konflux_environment.load()   # populate env vars

Usage as CLI:
    python3 scripts/konflux_environment.py                     # show env var table
    python3 scripts/konflux_environment.py --validate          # check required vars
    python3 scripts/konflux_environment.py --check-connectivity # GitLab + Konflux probe
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = _REPO_ROOT / ".work" / ".env"

REQUIRED_VARS: list[str] = ["GITLAB_HOST", "KONFLUX_CLUSTER_DOMAIN"]

_DERIVED: list[tuple[str, str]] = [
    ("KONFLUX_CLUSTER_ID", "{cluster_id}"),
    ("KONFLUX_INTERNAL_API", "https://api.{domain}.openshiftapps.com:6443"),
    ("TEKTON_RESULTS_API_DOMAIN", "tekton-results-tekton-results.apps.{domain}.openshiftapps.com"),
]

_PLACEHOLDER_PATTERNS: list[str] = [
    r"^test\.example\.com$",
    r"^example\.com$",
    r"\.example\.(com|org|net)$",
    r"^localhost",
    r"^my\.",
    r"^changeme",
    r"(?i)^TODO",
    r"(?i)^REPLACE.ME",
]

_SERVICE_VARS: dict[str, list[str]] = {
    "gitlab": ["GITLAB_HOST"],
}

CONNECTIVITY_STATE_DIR = Path.home() / ".config" / "aiops-infra"
CONNECTIVITY_STATE_FILE = CONNECTIVITY_STATE_DIR / ".connectivity.json"
CONNECTIVITY_TTL_HOURS = 24

_DISPLAY_VARS: list[tuple[str, bool]] = [
    ("GITLAB_HOST", False),
    ("GITLAB_PROJECT", False),
    ("GITLAB_TOKEN", True),
    ("KONFLUX_TENANT", False),
    ("PREFERRED_KONFLUX_CLUSTER", False),
    ("KONFLUX_CLUSTER_DOMAIN", False),
    ("KONFLUX_CLUSTER_ID", False),
    ("KONFLUX_EXTERNAL_API", False),
    ("KONFLUX_INTERNAL_API", False),
    ("TEKTON_RESULTS_API_DOMAIN", False),
    ("KONFLUX_NAMESPACE", False),
    ("KONFLUX_CONFORMA_POLICY_DIR", False),
    ("JIRA_EMAIL", False),
    ("JIRA_API_TOKEN", True),
]


@dataclass
class ValidationResult:
    """Structured validation result with three failure modes."""

    ok: bool
    missing: list[str] = field(default_factory=list)
    placeholders: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class ConnectivityResult:
    """Result of a live connectivity check against GitLab and optionally Konflux."""

    gitlab_dns: bool = False
    gitlab_https: bool = False
    gitlab_auth: bool | None = None
    gitlab_project: bool | None = None
    konflux_reachable: bool | None = None
    error_details: dict[str, str] = field(default_factory=dict)


_loaded = False


def _load_dotenv(populated: dict[str, str]) -> None:
    """Load .work/.env file into os.environ. Does not overwrite existing vars.

    Format: KEY=VALUE (one per line). Lines starting with # are comments.
    Supports optional quoting: KEY="VALUE" or KEY='VALUE'.
    """
    if not DOTENV_PATH.is_file():
        return
    try:
        for line in DOTENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            if not key or not value:
                continue
            if os.environ.get(key):
                continue
            os.environ[key] = value
            populated[key] = value
    except OSError:
        pass


def _resolve_jira_email(populated: dict[str, str]) -> None:
    """Derive and validate JIRA_EMAIL when only JIRA_API_TOKEN is set.

    Strategy:
      1. Try $USER@redhat.com (Jira accepts any @redhat.com prefix with a
         valid token and returns the real email from the account)
      2. On success: save the confirmed email to os.environ AND .work/.env
      3. On failure: print clear instructions for the user
    """
    if os.environ.get("JIRA_EMAIL"):
        return
    if not os.environ.get("JIRA_API_TOKEN"):
        return

    import getpass

    token = os.environ["JIRA_API_TOKEN"]
    candidate = f"{getpass.getuser()}@redhat.com"

    verified_email = _verify_jira_email(candidate, token)
    if verified_email:
        os.environ["JIRA_EMAIL"] = verified_email
        populated["JIRA_EMAIL"] = verified_email
        _append_to_dotenv("JIRA_EMAIL", verified_email)
    else:
        print(
            f"WARNING: Could not authenticate to Jira with '{candidate}'.\n"
            f"  Add your Jira email manually to .work/.env:\n"
            f"    JIRA_EMAIL=your.actual.email@redhat.com\n"
            f"  (The email associated with your Atlassian account at redhat.atlassian.net)",
            file=sys.stderr,
        )


def _verify_jira_email(email: str, token: str) -> str | None:
    """Validate email:token against Jira /myself. Returns confirmed email or None."""
    import base64
    import urllib.error
    import urllib.request

    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    url = "https://redhat.atlassian.net/rest/api/3/myself"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _json

            data = _json.loads(resp.read())
            return data.get("emailAddress", email)
    except urllib.error.HTTPError:
        return None
    except (urllib.error.URLError, OSError):
        return None


def _append_to_dotenv(key: str, value: str) -> None:
    """Save a key=value to .work/.env.

    If the key already exists with a non-empty value, do nothing.
    If the key exists with an empty value, update it in place.
    Otherwise append.
    """
    if not DOTENV_PATH.is_file():
        return
    try:
        lines = DOTENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
        found_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            k, v = stripped.split("=", 1)
            if k.strip() == key:
                if v.strip():
                    return
                found_idx = i
                break

        if found_idx is not None:
            lines[found_idx] = f"{key}={value}\n"
        else:
            lines.append(f"{key}={value}\n")

        DOTENV_PATH.write_text("".join(lines), encoding="utf-8")
    except OSError:
        pass


def _derive_from_cluster_domain(populated: dict[str, str]) -> None:
    """Derive secondary env vars from KONFLUX_CLUSTER_DOMAIN."""
    domain = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
    if not domain:
        return
    cluster_id = domain.split(".")[0]
    for env_var, fmt in _DERIVED:
        if os.environ.get(env_var):
            continue
        value = fmt.format(domain=domain, cluster_id=cluster_id)
        os.environ[env_var] = value
        populated[env_var] = value


def _populate_from_discovery(ctx, populated: dict[str, str]) -> None:
    """Set env vars from discovery result. Never overwrites existing vars."""
    if not os.environ.get("KONFLUX_CLUSTER_DOMAIN"):
        os.environ["KONFLUX_CLUSTER_DOMAIN"] = ctx.cluster.cluster_domain
        populated["KONFLUX_CLUSTER_DOMAIN"] = ctx.cluster.cluster_domain
        _derive_from_cluster_domain(populated)

    if ctx.conforma_policy_dir and not os.environ.get("KONFLUX_CONFORMA_POLICY_DIR"):
        os.environ["KONFLUX_CONFORMA_POLICY_DIR"] = ctx.conforma_policy_dir
        populated["KONFLUX_CONFORMA_POLICY_DIR"] = ctx.conforma_policy_dir

    if ctx.conforma_policy_files and not os.environ.get("KONFLUX_CONFORMA_POLICY_FILES"):
        val = ",".join(ctx.conforma_policy_files)
        os.environ["KONFLUX_CONFORMA_POLICY_FILES"] = val
        populated["KONFLUX_CONFORMA_POLICY_FILES"] = val

    if ctx.rpa_dir and not os.environ.get("KONFLUX_RPA_SUBPATH"):
        os.environ["KONFLUX_RPA_SUBPATH"] = ctx.rpa_dir
        populated["KONFLUX_RPA_SUBPATH"] = ctx.rpa_dir

    if ctx.self_service_files and not os.environ.get("KONFLUX_SELF_SERVICE_FILES"):
        val = ",".join(ctx.self_service_files)
        os.environ["KONFLUX_SELF_SERVICE_FILES"] = val
        populated["KONFLUX_SELF_SERVICE_FILES"] = val

    if not os.environ.get("KONFLUX_APPLICATION_SLUG") and ctx.rpa_subdirs:
        if len(ctx.rpa_subdirs) == 1:
            slug = ctx.rpa_subdirs[0]
            os.environ["KONFLUX_APPLICATION_SLUG"] = slug
            populated["KONFLUX_APPLICATION_SLUG"] = slug


def load() -> dict[str, str]:
    """Load environment and populate variables.

    Loads from .work/.env, derives secondary vars from KONFLUX_CLUSTER_DOMAIN,
    and triggers tenant auto-discovery when KONFLUX_TENANT is set but cluster is unknown.

    Returns a dict of {env_var: value} for all variables that were set.
    Env vars that are already set are NOT overwritten.
    """
    global _loaded
    if _loaded:
        return {}

    populated: dict[str, str] = {}

    _load_dotenv(populated)
    _resolve_jira_email(populated)
    _derive_from_cluster_domain(populated)

    tenant = os.environ.get("KONFLUX_TENANT")
    preferred = os.environ.get("PREFERRED_KONFLUX_CLUSTER")
    if tenant and not os.environ.get("KONFLUX_CLUSTER_DOMAIN"):
        try:
            import konflux_tenant_env_discovery

            context = konflux_tenant_env_discovery.discover(tenant, preferred_cluster=preferred)
            _populate_from_discovery(context, populated)
        except konflux_tenant_env_discovery.DiscoveryError as exc:
            print(f"WARNING: Konflux tenant environment discovery failed: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"WARNING: Konflux tenant environment discovery error: {exc}", file=sys.stderr)

    _loaded = True
    return populated


def validate() -> ValidationResult:
    """Check that all required env vars are set and not placeholders.

    Returns a ValidationResult with:
    - ok: True only if no missing and no placeholders
    - missing: list of required var names that are empty/unset
    - placeholders: list of (var_name, value, matched_pattern) for detected fakes
    """
    missing: list[str] = []
    placeholders: list[tuple[str, str, str]] = []
    for env_var in REQUIRED_VARS:
        value = os.environ.get(env_var, "")
        if not value:
            missing.append(env_var)
            continue
        for pattern in _PLACEHOLDER_PATTERNS:
            if re.search(pattern, value):
                placeholders.append((env_var, value, pattern))
                break
    ok = len(missing) == 0 and len(placeholders) == 0
    return ValidationResult(ok=ok, missing=missing, placeholders=placeholders)


def print_validation_failure(result: ValidationResult, file=sys.stderr) -> None:
    """Print machine-parseable + human-readable validation failure to file."""
    for var in result.missing:
        print(f"MISSING: {var}", file=file)
    for var_name, value, _pattern in result.placeholders:
        print(f"PLACEHOLDER: {var_name}={value}", file=file)
    print(file=file)
    if result.missing:
        print("Required environment variables are not set.", file=file)
    if result.placeholders:
        print("Environment contains placeholder values (not real infrastructure).", file=file)
    print(
        "\nFix by adding real values to .work/.env:\n"
        "  GITLAB_HOST=your-gitlab-host\n"
        "  KONFLUX_CLUSTER_DOMAIN=your-cluster-domain\n"
        "\nOr set KONFLUX_TENANT in .work/.env for auto-discovery.",
        file=file,
    )


def require(service: str) -> None:
    """Assert that config for a specific service is valid. Exits on failure.

    Call at the entry point of scripts that need a specific service:
        konflux_environment.require("gitlab")

    Supported services: "gitlab"
    """
    load()
    vars_to_check = _SERVICE_VARS.get(service)
    if vars_to_check is None:
        print(f"ERROR: Unknown service '{service}' passed to konflux_environment.require()", file=sys.stderr)
        sys.exit(1)
    result = validate()
    relevant_missing = [v for v in result.missing if v in vars_to_check]
    relevant_placeholders = [(v, val, p) for v, val, p in result.placeholders if v in vars_to_check]
    if relevant_missing or relevant_placeholders:
        print(f"ERROR: Environment for '{service}' is not usable.", file=sys.stderr)
        for var in relevant_missing:
            print(f"  MISSING: {var}", file=sys.stderr)
        for var_name, value, _p in relevant_placeholders:
            print(f"  PLACEHOLDER: {var_name}={value}", file=sys.stderr)
        print(
            f"\nFix by adding the required values to .work/.env:\n"
            f"  {chr(10).join(f'{v}=...' for v in vars_to_check)}",
            file=sys.stderr,
        )
        sys.exit(1)


def check_connectivity() -> ConnectivityResult:
    """Run a deterministic connectivity check against GitLab and optionally Konflux.

    GitLab checks (in order): DNS -> HTTPS -> Auth -> Project access.
    On full GitLab success, writes .connectivity.json state file.

    Konflux check (optional, informational): oc/kubectl whoami against the cluster.
    Konflux failure does NOT block the state file write or overall success.
    """
    import socket
    import urllib.error
    import urllib.request

    result = ConnectivityResult()
    host = os.environ.get("GITLAB_HOST", "")
    project = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")

    if not host:
        result.error_details["dns"] = "GITLAB_HOST is not set"
        return result

    try:
        socket.getaddrinfo(host, 443)
        result.gitlab_dns = True
    except (socket.gaierror, OSError) as exc:
        result.error_details["dns"] = f"Cannot resolve {host}: {exc}"
        return result

    try:
        import ssl

        url = f"https://{host}/api/v4/version"
        req = urllib.request.Request(url, method="GET")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                result.gitlab_https = resp.status < 400 or resp.status == 401
        except urllib.error.URLError as ssl_exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(ssl_exc):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                    result.gitlab_https = resp.status < 400 or resp.status == 401
            else:
                raise
    except urllib.error.HTTPError:
        result.gitlab_https = True
    except (urllib.error.URLError, OSError) as exc:
        result.error_details["https"] = f"Cannot reach https://{host}: {exc}"
        return result

    try:
        import gitlab_ops

        token = gitlab_ops.discover_token(f"https://{host}")
    except Exception:
        token = os.environ.get("GITLAB_TOKEN")

    if not token:
        result.gitlab_auth = None
        result.error_details["auth"] = (
            f"No GitLab token found for {host}. "
            "Set GITLAB_TOKEN or configure glab: glab auth login --hostname " + host
        )
        return result

    ssl_verify = os.environ.get("GITLAB_SSL_VERIFY", "true").lower() not in ("false", "0", "no")

    try:
        import gitlab as _gitlab_mod

        gl = _gitlab_mod.Gitlab(url=f"https://{host}", private_token=token, ssl_verify=ssl_verify)
        gl.auth()
        result.gitlab_auth = True
    except Exception as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc) and ssl_verify:
            try:
                gl = _gitlab_mod.Gitlab(url=f"https://{host}", private_token=token, ssl_verify=False)
                gl.auth()
                result.gitlab_auth = True
            except Exception as inner_exc:
                result.gitlab_auth = False
                result.error_details["auth"] = f"GitLab token rejected: {inner_exc}"
                return result
        else:
            result.gitlab_auth = False
            result.error_details["auth"] = f"GitLab token rejected: {exc}"
            return result

    try:
        gl.projects.get(project)
        result.gitlab_project = True
    except Exception as exc:
        result.gitlab_project = False
        result.error_details["project"] = f"Cannot access project '{project}': {exc}"
        return result

    _write_connectivity_state(host, project)

    _check_konflux_connectivity(result)

    return result


def _check_konflux_connectivity(result: ConnectivityResult) -> None:
    """Optional Konflux cluster probe via oc/kubectl whoami.

    This is informational only — failure does NOT affect GitLab connectivity
    state or the overall connectivity_confirmed() result.
    """
    external_api = os.environ.get("KONFLUX_EXTERNAL_API", "")
    if not external_api:
        result.konflux_reachable = None
        return

    oc_path = shutil.which("oc")
    kubectl_path = shutil.which("kubectl")
    cli = oc_path or kubectl_path

    if not cli:
        result.konflux_reachable = None
        result.error_details["konflux"] = (
            "Neither 'oc' nor 'kubectl' found on PATH. "
            "Install one to enable Konflux connectivity checks."
        )
        return

    try:
        proc = subprocess.run(
            [cli, "whoami", f"--server={external_api}"],
            capture_output=True,
            text=True,
            timeout=15,
            close_fds=True,
        )
        if proc.returncode == 0:
            result.konflux_reachable = True
        else:
            result.konflux_reachable = False
            result.error_details["konflux"] = (
                f"Konflux cluster not reachable or not authenticated "
                f"(server={external_api}): {proc.stderr.strip()}\n"
                f"  Without authenticated access to Konflux, some operations "
                f"(running Konflux-based Conforma, fetching some reports) won't be possible."
            )
    except subprocess.TimeoutExpired:
        result.konflux_reachable = False
        result.error_details["konflux"] = (
            f"Timed out connecting to Konflux cluster at {external_api}.\n"
            f"  Without authenticated access to Konflux, some operations "
            f"(running Konflux-based Conforma, fetching some reports) won't be possible."
        )
    except (FileNotFoundError, OSError) as exc:
        result.konflux_reachable = False
        result.error_details["konflux"] = f"Failed to run {cli}: {exc}"


def _write_connectivity_state(host: str, project: str) -> None:
    """Write successful connectivity state to disk."""
    from datetime import datetime, timezone

    CONNECTIVITY_STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "gitlab_host": host,
        "project": project,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ttl_hours": CONNECTIVITY_TTL_HOURS,
    }
    CONNECTIVITY_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def connectivity_confirmed() -> bool:
    """Check if connectivity was recently confirmed (within TTL).

    Returns True only if: file exists, gitlab_host matches current config,
    and checked_at is within ttl_hours.
    """
    if not CONNECTIVITY_STATE_FILE.is_file():
        return False
    try:
        state = json.loads(CONNECTIVITY_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    current_host = os.environ.get("GITLAB_HOST", "")
    if state.get("gitlab_host") != current_host:
        return False

    from datetime import datetime, timezone

    try:
        checked = datetime.fromisoformat(state["checked_at"])
        ttl = state.get("ttl_hours", CONNECTIVITY_TTL_HOURS)
        age_hours = (datetime.now(timezone.utc) - checked).total_seconds() / 3600
        return age_hours < ttl
    except (KeyError, ValueError, TypeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Konflux environment for aiops-infra")
    parser.add_argument("--validate", action="store_true", help="Check all required vars are set and not placeholders")
    parser.add_argument("--check-connectivity", action="store_true", help="Verify live connectivity to GitLab and Konflux")
    args = parser.parse_args()

    populated = load()

    if args.check_connectivity:
        gitlab_host = os.environ.get("GITLAB_HOST", "")
        if not gitlab_host:
            print("ERROR: GITLAB_HOST is not set. Cannot check connectivity.", file=sys.stderr)
            print("  Fix: add GITLAB_HOST=your-host to .work/.env", file=sys.stderr)
            return 1
        for pattern in _PLACEHOLDER_PATTERNS:
            if re.search(pattern, gitlab_host):
                print(f"ERROR: GITLAB_HOST='{gitlab_host}' looks like a placeholder.", file=sys.stderr)
                print("  Fix: set a real GITLAB_HOST value in .work/.env", file=sys.stderr)
                return 2
        conn = check_connectivity()
        if conn.gitlab_dns and conn.gitlab_https and conn.gitlab_auth and conn.gitlab_project:
            print("Connectivity OK: GitLab DNS, HTTPS, auth, and project access all verified.")
        else:
            if not conn.gitlab_dns:
                print(f"ERROR: {conn.error_details.get('dns', 'DNS resolution failed')}", file=sys.stderr)
                print("  Check: is the hostname correct? Is your network/VPN active?", file=sys.stderr)
                return 3
            if not conn.gitlab_https:
                print(f"ERROR: {conn.error_details.get('https', 'HTTPS connection failed')}", file=sys.stderr)
                print("  Check: is your VPN connected? Can you reach this host in a browser?", file=sys.stderr)
                return 4
            if conn.gitlab_auth is None or conn.gitlab_auth is False:
                print(f"ERROR: {conn.error_details.get('auth', 'Authentication failed')}", file=sys.stderr)
                print("  Check: set GITLAB_TOKEN or run: glab auth login --hostname $GITLAB_HOST", file=sys.stderr)
                return 5
            if conn.gitlab_project is False:
                print(f"ERROR: {conn.error_details.get('project', 'Project access denied')}", file=sys.stderr)
                print("  Check: does your token have access to the configured GITLAB_PROJECT?", file=sys.stderr)
                return 6

        if conn.konflux_reachable is True:
            print("Konflux OK: cluster authenticated.")
        elif conn.konflux_reachable is False:
            print(f"WARNING: {conn.error_details.get('konflux', 'Konflux cluster not reachable')}", file=sys.stderr)
        elif conn.konflux_reachable is None and conn.error_details.get("konflux"):
            print(f"NOTE: {conn.error_details['konflux']}", file=sys.stderr)
        else:
            print("NOTE: KONFLUX_EXTERNAL_API not set — skipping Konflux connectivity check.")

        return 0

    if args.validate:
        result = validate()
        if result.ok:
            print("All required environment variables are set.")
            return 0
        print_validation_failure(result)
        if result.placeholders:
            return 2
        return 1

    print(f"Environment loaded ({len(populated)} variable(s) populated).\n")

    for env_var, masked in _DISPLAY_VARS:
        val = os.environ.get(env_var, "")
        required = env_var in REQUIRED_VARS
        marker = "*" if required else " "
        if not val:
            val_display = "(unset)"
        elif masked and val:
            val_display = val[:4] + "****" if len(val) > 4 else "****"
        elif len(val) > 50:
            val_display = val[:47] + "..."
        else:
            val_display = val
        print(f"  {marker} {env_var:35s} = {val_display}")

    print("\n  * = required")
    return 0


if __name__ == "__main__":
    sys.exit(main())
