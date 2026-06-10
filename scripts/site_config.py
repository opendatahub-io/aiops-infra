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
import subprocess
import sys
import time
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
    ("component_catalog.gitlab_project", "COMPONENT_CATALOG_PROJECT", False),
    ("slack.workspace_url", "SLACK_WORKSPACE_URL", False),
]

_DERIVED: list[tuple[str, str]] = [
    ("KRD_CLUSTER_ID", "{cluster_id}"),
    ("KONFLUX_INTERNAL_API", "https://api.{domain}.openshiftapps.com:6443"),
    ("TEKTON_RESULTS_DOMAIN", "tekton-results-tekton-results.apps.{domain}.openshiftapps.com"),
]

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
            if not key:
                continue
            if os.environ.get(key):
                continue
            os.environ[key] = value
            populated[key] = value
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
    _derive_from_cluster_domain(populated)

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


def validate() -> tuple[bool, list[str]]:
    """Check that all required env vars are set (after load).

    Returns (all_ok, list_of_missing_var_names).
    """
    missing = []
    for _dotpath, env_var, required in _FIELD_MAP:
        if required and not os.environ.get(env_var):
            missing.append(env_var)
    return len(missing) == 0, missing


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
    parser.add_argument("--validate", action="store_true", help="Check all required vars are set")
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

    if args.validate:
        ok, missing = validate()
        if ok:
            print("All required site config variables are set.")
            return 0
        print("Missing required site config variables:", file=sys.stderr)
        for var in missing:
            print(f"  {var}", file=sys.stderr)
        src = config_source()
        print(f"\nConfig source: {src}", file=sys.stderr)
        if src == "none":
            print(
                "\nRun 'python3 scripts/site_config.py --refresh' to fetch the team config,\n"
                "or copy site-config.example.yaml to ~/.config/aiops-infra/site-config.yaml.",
                file=sys.stderr,
            )
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
