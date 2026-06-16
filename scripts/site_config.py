"""Site configuration loader for aiops-infra (dual-mode: CLI + importable).

Loads infrastructure-specific values from a YAML site config and populates
environment variables. This bridges public skills with private internal config.

Search order (first match wins):
  1. Environment variables already set (never overwritten)
  2. $AIOPS_SITE_CONFIG  (explicit config path)
  3. ~/.config/aiops-infra/site-config.yaml  (user-level local config)
  4. ~/.config/aiops-infra/.remote-cache/site-config.yaml  (auto-managed remote cache)

Remote fetch:
  When no local config exists, the loader can fetch the team's canonical config
  from a private GitHub repo via ``gh api``.  The fetched file is cached locally
  with a 72-hour TTL.  Override the URL with $CONFORMA_SKILL_SITE_CONFIG_URL.

Usage as library:
    import site_config
    site_config.load()   # populate env vars from site config

Usage as CLI:
    python3 scripts/site_config.py              # show loaded config
    python3 scripts/site_config.py --validate   # check all required vars are set
    python3 scripts/site_config.py --export     # print shell export statements
    python3 scripts/site_config.py --refresh    # force refetch from remote
    python3 scripts/site_config.py --show-source  # print config source
    python3 scripts/site_config.py --write-local KEY=VALUE ...  # write to local config
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_SEARCH_PATHS = [
    Path(os.environ.get("AIOPS_SITE_CONFIG", "")) if os.environ.get("AIOPS_SITE_CONFIG") else None,
    Path.home() / ".config" / "aiops-infra" / "site-config.yaml",
]

_REPO_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = _REPO_ROOT / ".work" / ".env"

REMOTE_CACHE_DIR = Path.home() / ".config" / "aiops-infra" / ".remote-cache"
REMOTE_CACHE_FILE = REMOTE_CACHE_DIR / "site-config.yaml"
CACHE_TTL_HOURS = 72

DEFAULT_REMOTE_CONFIG_URL = (
    "repos/red-hat-data-services/rhods-devops-infra/contents/src/config/conforma-skill-site-config.yaml?ref=main"
)

_FIELD_MAP: list[tuple[str, str, bool]] = [
    # (yaml_dotpath, env_var_name, required)
    ("gitlab.host", "GITLAB_HOST", True),
    ("gitlab.project", "GITLAB_PROJECT", False),
    ("konflux.external_api", "KONFLUX_EXTERNAL_API", False),
    ("konflux.internal_api", "KONFLUX_INTERNAL_API", False),
    ("konflux.namespace", "KONFLUX_NAMESPACE", False),
    ("konflux.cluster_domain", "KRD_CLUSTER_DOMAIN", True),
    ("tenant", "TENANT", False),
    ("preferred_cluster", "PREFERRED_CLUSTER", False),
    ("component_catalog.gitlab_project", "COMPONENT_CATALOG_PROJECT", False),
    ("slack.workspace_url", "SLACK_WORKSPACE_URL", False),
]

_DERIVED: list[tuple[str, str]] = [
    ("KRD_CLUSTER_ID", "{cluster_id}"),
    ("KONFLUX_INTERNAL_API", "https://api.{domain}.openshiftapps.com:6443"),
    ("TEKTON_RESULTS_DOMAIN", "tekton-results-tekton-results.apps.{domain}.openshiftapps.com"),
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


@dataclass
class ValidationResult:
    """Structured validation result with three failure modes."""

    ok: bool
    missing: list[str] = field(default_factory=list)
    placeholders: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class ConnectivityResult:
    """Result of a live connectivity check against GitLab."""

    gitlab_dns: bool = False
    gitlab_https: bool = False
    gitlab_auth: bool | None = None
    gitlab_project: bool | None = None
    error_details: dict[str, str] = field(default_factory=dict)


_loaded = False


def _resolve_yaml_path(data: dict, dotpath: str) -> str | None:
    """Resolve a dot-separated path in a nested dict."""
    keys = dotpath.split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return str(current) if current else None


def _set_yaml_path(data: dict, dotpath: str, value: str) -> None:
    """Set a value at a dot-separated path, creating intermediate dicts."""
    keys = dotpath.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def _is_cache_fresh(path: Path) -> bool:
    """Check if cached file is younger than CACHE_TTL_HOURS."""
    if not path.is_file():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < CACHE_TTL_HOURS


def _fetch_remote_config() -> str | None:
    """Fetch site config from a private GitHub repo via ``gh api``.

    Returns file content as a string, or None on failure.
    """
    url = os.environ.get("CONFORMA_SKILL_SITE_CONFIG_URL", DEFAULT_REMOTE_CONFIG_URL)
    try:
        result = subprocess.run(
            ["gh", "api", url, "--jq", ".content"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None

        import base64

        content = base64.b64decode(result.stdout.strip()).decode("utf-8")
        test_data = yaml.safe_load(content)
        if not isinstance(test_data, dict):
            return None
        return content
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return None


def _save_remote_cache(content: str) -> Path:
    """Save fetched content to the remote cache directory."""
    REMOTE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REMOTE_CACHE_FILE.write_text(content, encoding="utf-8")
    return REMOTE_CACHE_FILE


def find_config() -> Path | None:
    """Find the first existing site config file.

    Checks local paths first, then the remote cache (fetching if stale/missing).
    """
    for candidate in CONFIG_SEARCH_PATHS:
        if candidate and candidate.is_file():
            return candidate

    if _is_cache_fresh(REMOTE_CACHE_FILE):
        return REMOTE_CACHE_FILE

    content = _fetch_remote_config()
    if content:
        return _save_remote_cache(content)

    if REMOTE_CACHE_FILE.is_file():
        print("Warning: remote config cache is stale but refetch failed; using stale cache.", file=sys.stderr)
        return REMOTE_CACHE_FILE

    return None


def config_source() -> str:
    """Return a human-readable description of where config was loaded from."""
    for candidate in CONFIG_SEARCH_PATHS:
        if candidate and candidate.is_file():
            if candidate == CONFIG_SEARCH_PATHS[0]:
                return f"explicit ($AIOPS_SITE_CONFIG): {candidate}"
            return f"local: {candidate}"
    if REMOTE_CACHE_FILE.is_file():
        age_hours = (time.time() - REMOTE_CACHE_FILE.stat().st_mtime) / 3600
        fresh = "fresh" if age_hours < CACHE_TTL_HOURS else "stale"
        return f"remote cache ({fresh}, {age_hours:.0f}h old): {REMOTE_CACHE_FILE}"
    return "none"


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
            import json

            data = json.loads(resp.read())
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


def load(config_path: Path | None = None) -> dict[str, str]:
    """Load site config and populate environment variables.

    Loads from three sources (first value wins, existing env vars never overwritten):
      1. Environment variables already set
      2. YAML site-config (local or remote-cached)
      3. .work/.env file (secrets like JIRA_API_TOKEN)

    Returns a dict of {env_var: value} for all variables that were set.
    Env vars that are already set are NOT overwritten.
    """
    global _loaded
    if _loaded and config_path is None:
        return {}

    path = config_path or find_config()
    populated: dict[str, str] = {}

    if path and path.is_file():
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            data = {}

        for dotpath, env_var, _required in _FIELD_MAP:
            if os.environ.get(env_var):
                continue
            value = _resolve_yaml_path(data, dotpath)
            if value:
                os.environ[env_var] = value
                populated[env_var] = value

    _load_dotenv(populated)
    _resolve_jira_email(populated)
    _derive_from_cluster_domain(populated)

    tenant = os.environ.get("TENANT")
    preferred = os.environ.get("PREFERRED_CLUSTER")
    if tenant and not os.environ.get("KRD_CLUSTER_DOMAIN"):
        if not connectivity_confirmed():
            print(
                "ERROR: Cannot run tenant discovery — connectivity not confirmed.\n"
                "Run: python3 scripts/site_config.py --check-connectivity",
                file=sys.stderr,
            )
        else:
            try:
                import tenant_discovery

                context = tenant_discovery.discover(tenant, preferred_cluster=preferred)
                _populate_from_discovery(context, populated)
            except tenant_discovery.DiscoveryError as exc:
                print(f"WARNING: Tenant discovery failed: {exc}", file=sys.stderr)
            except Exception as exc:
                print(f"WARNING: Tenant discovery error: {exc}", file=sys.stderr)

    if populated and not connectivity_confirmed():
        print(
            "WARNING: Site config has NOT been checked against live infrastructure.\n"
            "Results may be unreliable. Run: python3 scripts/site_config.py --check-connectivity",
            file=sys.stderr,
        )

    _loaded = True
    return populated


def _derive_from_cluster_domain(populated: dict[str, str]) -> None:
    """Derive secondary env vars from KRD_CLUSTER_DOMAIN."""
    domain = os.environ.get("KRD_CLUSTER_DOMAIN", "")
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
    if not os.environ.get("KRD_CLUSTER_DOMAIN"):
        os.environ["KRD_CLUSTER_DOMAIN"] = ctx.cluster.cluster_domain
        populated["KRD_CLUSTER_DOMAIN"] = ctx.cluster.cluster_domain
        _derive_from_cluster_domain(populated)

    if ctx.ec_policy_dir and not os.environ.get("KRD_EC_POLICY_DIR"):
        os.environ["KRD_EC_POLICY_DIR"] = ctx.ec_policy_dir
        populated["KRD_EC_POLICY_DIR"] = ctx.ec_policy_dir

    if ctx.ec_policy_files and not os.environ.get("KRD_EC_POLICY_FILES"):
        val = ",".join(ctx.ec_policy_files)
        os.environ["KRD_EC_POLICY_FILES"] = val
        populated["KRD_EC_POLICY_FILES"] = val

    if ctx.rpa_dir and not os.environ.get("KRD_RPA_SUBPATH"):
        os.environ["KRD_RPA_SUBPATH"] = ctx.rpa_dir
        populated["KRD_RPA_SUBPATH"] = ctx.rpa_dir

    if ctx.self_service_files and not os.environ.get("KRD_SELF_SERVICE_FILES"):
        val = ",".join(ctx.self_service_files)
        os.environ["KRD_SELF_SERVICE_FILES"] = val
        populated["KRD_SELF_SERVICE_FILES"] = val


def validate() -> ValidationResult:
    """Check that all required env vars are set and not placeholders.

    Returns a ValidationResult with:
    - ok: True only if no missing and no placeholders
    - missing: list of required var names that are empty/unset
    - placeholders: list of (var_name, value, matched_pattern) for detected fakes
    """
    missing: list[str] = []
    placeholders: list[tuple[str, str, str]] = []
    for _dotpath, env_var, required in _FIELD_MAP:
        if not required:
            continue
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
        print("Required site config variables are not set.", file=file)
    if result.placeholders:
        print("Site config contains placeholder values (not real infrastructure).", file=file)
    print(
        "\nFix with:\n"
        "  python3 scripts/site_config.py --refresh         (auto-fetch team config)\n"
        "  python3 scripts/site_config.py --write-local gitlab.host=REAL_HOST ...",
        file=file,
    )


def require(service: str) -> None:
    """Assert that config for a specific service is valid. Exits on failure.

    Call at the entry point of scripts that need a specific service:
        site_config.require("gitlab")

    Supported services: "gitlab"
    """
    load()
    vars_to_check = _SERVICE_VARS.get(service)
    if vars_to_check is None:
        print(f"ERROR: Unknown service '{service}' passed to site_config.require()", file=sys.stderr)
        sys.exit(1)
    result = validate()
    relevant_missing = [v for v in result.missing if v in vars_to_check]
    relevant_placeholders = [(v, val, p) for v, val, p in result.placeholders if v in vars_to_check]
    if relevant_missing or relevant_placeholders:
        print(f"ERROR: Site config for '{service}' is not usable.", file=sys.stderr)
        for var in relevant_missing:
            print(f"  MISSING: {var}", file=sys.stderr)
        for var_name, value, _p in relevant_placeholders:
            print(f"  PLACEHOLDER: {var_name}={value}", file=sys.stderr)
        print(
            f"\nFix with:\n"
            f"  python3 scripts/site_config.py --refresh\n"
            f"  python3 scripts/site_config.py --write-local {' '.join(f'{v}=...' for v in vars_to_check)}",
            file=sys.stderr,
        )
        sys.exit(1)


def check_connectivity() -> ConnectivityResult:
    """Run a deterministic connectivity check against the configured GitLab.

    Checks (in order): DNS → HTTPS → Auth → Project access.
    On full success, writes .connectivity.json state file.
    """
    import socket
    import urllib.request
    import urllib.error

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
    except urllib.error.HTTPError as exc:
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
    return result


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


def get_status() -> dict:
    """Return current config status for display."""
    config_file = find_config()
    entries = []
    for dotpath, env_var, required in _FIELD_MAP:
        val = os.environ.get(env_var, "")
        source = "env" if val else "unset"
        entries.append(
            {
                "env_var": env_var,
                "yaml_path": dotpath,
                "value": val if val else "",
                "source": source,
                "required": required,
            }
        )
    return {
        "config_file": str(config_file) if config_file else None,
        "config_source": config_source(),
        "entries": entries,
    }


def write_local(pairs: list[str]) -> dict:
    """Write key=value pairs to the local site-config file.

    Creates the file if it doesn't exist. Merges into existing content.
    Keys use yaml dotpath notation (e.g. ``gitlab.host``).
    """
    local_path = Path.home() / ".config" / "aiops-infra" / "site-config.yaml"
    local_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if local_path.is_file():
        try:
            with open(local_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            data = {}

    written = {}
    for pair in pairs:
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        _set_yaml_path(data, key.strip(), value.strip())
        written[key.strip()] = value.strip()

    with open(local_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return {"path": str(local_path), "written": written}


def refresh_remote() -> dict:
    """Force refetch from remote, update cache."""
    content = _fetch_remote_config()
    if content:
        path = _save_remote_cache(content)
        return {"ok": True, "path": str(path), "error": None}
    return {"ok": False, "path": None, "error": "Failed to fetch remote config (check gh auth and repo access)"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Site configuration for aiops-infra")
    parser.add_argument("--validate", action="store_true", help="Check all required vars are set and not placeholders")
    parser.add_argument("--check-connectivity", action="store_true", help="Verify live connectivity to GitLab")
    parser.add_argument("--export", action="store_true", help="Print shell export statements")
    parser.add_argument("--json", action="store_true", help="Output status as JSON")
    parser.add_argument("--refresh", action="store_true", help="Force refetch from remote config")
    parser.add_argument("--show-source", action="store_true", help="Print where config was loaded from")
    parser.add_argument("--write-local", nargs="+", metavar="KEY=VALUE", help="Write key=value pairs to local config")
    args = parser.parse_args()

    if args.refresh:
        result = refresh_remote()
        if result["ok"]:
            print(f"Remote config fetched and cached: {result['path']}")
            return 0
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1

    if args.write_local:
        result = write_local(args.write_local)
        print(f"Written to {result['path']}:")
        for k, v in result["written"].items():
            print(f"  {k} = {v}")
        return 0

    populated = load()

    if args.show_source:
        print(config_source())
        return 0

    if args.export:
        for env_var in sorted(populated):
            val = populated[env_var]
            print(f'export {env_var}="{val}"')
        return 0

    if args.json:
        print(json.dumps(get_status(), indent=2))
        return 0

    if args.check_connectivity:
        gitlab_host = os.environ.get("GITLAB_HOST", "")
        if not gitlab_host:
            print("ERROR: GITLAB_HOST is not set. Cannot check connectivity.", file=sys.stderr)
            print("  Fix: python3 scripts/site_config.py --write-local gitlab.host=YOUR_HOST", file=sys.stderr)
            return 1
        for pattern in _PLACEHOLDER_PATTERNS:
            if re.search(pattern, gitlab_host):
                print(f"ERROR: GITLAB_HOST='{gitlab_host}' looks like a placeholder.", file=sys.stderr)
                print("  Fix: python3 scripts/site_config.py --write-local gitlab.host=REAL_HOST", file=sys.stderr)
                return 2
        conn = check_connectivity()
        if conn.gitlab_dns and conn.gitlab_https and conn.gitlab_auth and conn.gitlab_project:
            print("Connectivity OK: GitLab DNS, HTTPS, auth, and project access all verified.")
            return 0
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
        return 0

    if args.validate:
        result = validate()
        if result.ok:
            print("All required site config variables are set.")
            return 0
        print_validation_failure(result)
        src = config_source()
        print(f"\nConfig source: {src}", file=sys.stderr)
        if result.placeholders:
            return 2
        return 1

    status = get_status()
    config_file = status["config_file"]
    print(f"Config file: {config_file or '(none found)'}")
    print(f"Config source: {status['config_source']}")
    if populated:
        print(f"Loaded {len(populated)} variable(s) from site config.")
    print()

    for entry in status["entries"]:
        marker = "*" if entry["required"] else " "
        val_display = entry["value"] or "(unset)"
        if entry["value"] and len(entry["value"]) > 40:
            val_display = entry["value"][:37] + "..."
        print(f"  {marker} {entry['env_var']:30s} = {val_display}")

    print("\n  * = required")
    return 0


if __name__ == "__main__":
    sys.exit(main())
