"""Site configuration loader for aiops-infra (dual-mode: CLI + importable).

Loads infrastructure-specific values from a YAML site config and populates
environment variables. This bridges public skills with private internal config.

Search order (first match wins):
  1. Environment variables already set (never overwritten)
  2. $AIOPS_SITE_CONFIG  (explicit config path)
  3. ~/.config/aiops-infra/site-config.yaml  (user-level default)

Usage as library:
    import site_config
    site_config.load()   # populate env vars from site config

Usage as CLI:
    python3 scripts/site_config.py              # show loaded config
    python3 scripts/site_config.py --validate   # check all required vars are set
    python3 scripts/site_config.py --export     # print shell export statements
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

CONFIG_SEARCH_PATHS = [
    Path(os.environ.get("AIOPS_SITE_CONFIG", "")) if os.environ.get("AIOPS_SITE_CONFIG") else None,
    Path.home() / ".config" / "aiops-infra" / "site-config.yaml",
]

_FIELD_MAP: list[tuple[str, str, bool]] = [
    # (yaml_dotpath, env_var_name, required)
    ("gitlab.host", "GITLAB_HOST", True),
    ("gitlab.project", "GITLAB_PROJECT", False),
    ("konflux.external_api", "KONFLUX_EXTERNAL_API", False),
    ("konflux.internal_api", "KONFLUX_INTERNAL_API", False),
    ("konflux.namespace", "KONFLUX_NAMESPACE", False),
    ("konflux.cluster_domain", "KRD_CLUSTER_DOMAIN", True),
]

# Variables derived from KRD_CLUSTER_DOMAIN (set only if not already present).
_DERIVED: list[tuple[str, str]] = [
    # (env_var, format_string using {domain} and {cluster_id})
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


def find_config() -> Path | None:
    """Find the first existing site config file."""
    for candidate in CONFIG_SEARCH_PATHS:
        if candidate and candidate.is_file():
            return candidate
    return None


def load(config_path: Path | None = None) -> dict[str, str]:
    """Load site config and populate environment variables.

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
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Site configuration for aiops-infra")
    parser.add_argument("--validate", action="store_true", help="Check all required vars are set")
    parser.add_argument("--export", action="store_true", help="Print shell export statements")
    parser.add_argument("--json", action="store_true", help="Output status as JSON")
    args = parser.parse_args()

    populated = load()

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
        print(
            "\nCopy site-config.example.yaml to ~/.config/aiops-infra/site-config.yaml and fill in your values.",
            file=sys.stderr,
        )
        return 1

    status = get_status()
    config_file = status["config_file"]
    print(f"Config file: {config_file or '(none found)'}")
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
