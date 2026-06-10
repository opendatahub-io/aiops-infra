"""component_catalog_ops.py -- Component catalog primitives (dual-mode: CLI + importable).

Resolves Konflux component names to Jira Component field values using the
component-maturity catalog from the internal GitLab ($GITLAB_HOST).

The catalog repo contains query.py (stdlib-only, local reads from bundled JSON)
that maps container image names to Jira components.  This module wraps it with
name normalization logic to bridge Konflux component naming (version-suffixed)
to container image naming (OS-suffixed or bare).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import site_config

site_config.load()

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CLONE_DIR = _REPO_ROOT / ".work" / "component-maturity"
_DEFAULT_PROJECT = "data-hub/component-maturity"

_VERSION_SUFFIX_RE = re.compile(r"-v\d+-\d+(-ea-\d+)?$")
_OS_SUFFIX_RE = re.compile(r"-(?:rhel|ubi)\d+$")


def _gitlab_host() -> str:
    host = os.environ.get("GITLAB_HOST", "")
    if not host:
        raise RuntimeError("GITLAB_HOST not set. Run: python3 scripts/site_config.py --validate")
    return host


def _catalog_project() -> str:
    return os.environ.get("COMPONENT_CATALOG_PROJECT", _DEFAULT_PROJECT)


def ensure_catalog_repo(clone_dir: Path | None = None) -> dict:
    """Clone or update the component-maturity repo.

    Returns {"ok": bool, "path": str, "error": str|None}.
    """
    target = clone_dir or _DEFAULT_CLONE_DIR
    target = Path(target)
    host = _gitlab_host()
    project = _catalog_project()

    if (target / ".git").is_dir():
        try:
            subprocess.run(
                ["git", "-C", str(target), "pull", "--ff-only"],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
            return {"ok": True, "path": str(target), "error": None}
        except subprocess.CalledProcessError as exc:
            return {"ok": False, "path": str(target), "error": f"git pull failed: {exc.stderr.strip()}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "path": str(target), "error": "git pull timed out"}

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        token_result = subprocess.run(
            ["glab", "config", "get", "token", "--host", host],
            capture_output=True,
            text=True,
            timeout=10,
        )
        token = token_result.stdout.strip() if token_result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        token = ""

    if not token:
        return {
            "ok": False,
            "path": str(target),
            "error": f"No GitLab token for {host}. Run: glab auth login --hostname {host}",
        }

    clone_url = f"https://oauth2:{token}@{host}/{project}.git"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(target)],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        return {"ok": True, "path": str(target), "error": None}
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "path": str(target), "error": f"git clone failed: {exc.stderr.strip()}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "path": str(target), "error": "git clone timed out"}


def _run_query(query_script: Path, tier: str) -> list[dict]:
    """Run query.py for a given tier and return the parsed artifact list."""
    result = subprocess.run(
        [
            sys.executable,
            str(query_script),
            "--rh_product",
            "Red Hat OpenShift AI",
            "--find",
            "artifacts",
            "--tier",
            tier,
            "--all-versions",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"query.py (tier={tier}) failed (exit {result.returncode}): {result.stderr.strip()}")
    data = json.loads(result.stdout)
    results = data.get("results", [])
    if not isinstance(results, list):
        raise RuntimeError(f"query.py returned unexpected format: expected list in 'results', got {type(results)}")
    return results


def load_catalog(clone_dir: Path | None = None) -> list[dict]:
    """Run query.py for downstream + midstream tiers and return merged results.

    Downstream is loaded first and takes priority when a name appears in
    both tiers.  Downstream entries carry exact image names
    (``odh-vllm-gaudi-rhel9``), ``repos``, and ``jira_components`` data.
    Midstream entries carry bare names (``vllm``) as a fallback.

    Raises RuntimeError if query.py is not found or returns bad data.
    """
    target = Path(clone_dir or _DEFAULT_CLONE_DIR)
    query_script = target / ".claude" / "skills" / "software-catalog-query" / "scripts" / "query.py"

    if not query_script.is_file():
        raise RuntimeError(
            f"query.py not found at {query_script}. Run: python3 scripts/component_catalog_ops.py ensure-repo"
        )

    downstream = _run_query(query_script, "downstream")
    midstream = _run_query(query_script, "midstream")

    seen: set[str] = set()
    merged: list[dict] = []
    for entry in downstream + midstream:
        name = entry.get("name", "")
        if name and name not in seen:
            seen.add(name)
            merged.append(entry)
    return merged


def _strip_version_suffix(name: str) -> str:
    """Strip Konflux version suffix: -v3-5, -v3-5-ea-1, -v2-25, etc."""
    return _VERSION_SUFFIX_RE.sub("", name)


def _strip_os_suffix(name: str) -> str:
    """Strip OS suffix: -rhel9, -ubi9, etc."""
    return _OS_SUFFIX_RE.sub("", name)


def _extract_jira_component(entry: dict) -> str | None:
    """Extract the Jira Component from a catalog entry.

    Handles both formats:
      - ``jira_component`` (str) -- downstream tier
      - ``jira_components`` (list[str]) -- midstream tier (takes first)
    """
    jc = entry.get("jira_component")
    if jc:
        return jc
    jcs = entry.get("jira_components")
    if isinstance(jcs, list) and jcs:
        return jcs[0]
    return None


def _build_lookup_index(catalog: list[dict]) -> dict[str, str]:
    """Build a normalized-name -> jira_component index from catalog entries.

    Creates entries for:
      - raw image name
      - OS-stripped variant (``-rhel9``, ``-ubi9``)
      - ``odh-`` prefixed variant (some Konflux names add ``odh-`` prefix)
      - repo basename (last path component of ``repos`` field, with ``odh-`` prefix)
    """
    index: dict[str, str] = {}
    for entry in catalog:
        name = entry.get("name", "")
        jira_comp = _extract_jira_component(entry)
        if not name or not jira_comp:
            continue
        index[name] = jira_comp
        stripped = _strip_os_suffix(name)
        if stripped != name:
            index.setdefault(stripped, jira_comp)
        prefixed = f"odh-{name}"
        index.setdefault(prefixed, jira_comp)
        if stripped != name:
            index.setdefault(f"odh-{stripped}", jira_comp)

        for repo in entry.get("repos", []):
            repo_basename = repo.rsplit("/", 1)[-1] if "/" in repo else repo
            if repo_basename:
                index.setdefault(repo_basename, jira_comp)
                index.setdefault(f"odh-{repo_basename}", jira_comp)
                norm = repo_basename.replace("_", "-")
                if norm != repo_basename:
                    index.setdefault(norm, jira_comp)
                    index.setdefault(f"odh-{norm}", jira_comp)
    return index


def _resolve_single(name: str, index: dict[str, str]) -> str | None:
    """Try all normalization strategies to resolve a name against the index."""
    if name in index:
        return index[name]

    ver_stripped = _strip_version_suffix(name)
    if ver_stripped in index:
        return index[ver_stripped]

    os_stripped = _strip_os_suffix(name)
    if os_stripped in index:
        return index[os_stripped]

    both_stripped = _strip_os_suffix(ver_stripped)
    if both_stripped != ver_stripped and both_stripped in index:
        return index[both_stripped]

    return None


def resolve_jira_component(konflux_name: str, catalog: list[dict]) -> str | None:
    """Resolve a single Konflux component name to a Jira Component.

    Matching strategy (first match wins):
      1. Exact match against catalog image names
      2. Strip version suffix, match
      3. Strip OS suffix, match
      4. Strip both, match
    All checked against index which includes raw names, OS-stripped, and odh-prefixed variants.
    """
    index = _build_lookup_index(catalog)
    return _resolve_single(konflux_name, index)


def resolve_jira_components(konflux_names: list[str], catalog: list[dict]) -> dict[str, str | None]:
    """Resolve multiple Konflux component names to Jira Components.

    Returns {konflux_name: jira_component_or_None}.
    """
    index = _build_lookup_index(catalog)
    return {name: _resolve_single(name, index) for name in konflux_names}


_EXCEPTION_LABEL_RE = re.compile(r"Exception[- ]([^:]+):(.+)")
_IMAGE_NAME_RE = re.compile(r"((?:odh|rhoai)-[a-z0-9][a-z0-9-]*-(?:rhel|ubi)\d+)")
_QUAY_IMAGE_RE = re.compile(r"quay\.io/rhoai/([a-z0-9][a-z0-9_-]+?)(?:@sha256:|[|,\s])")


def _extract_adf_text(node: dict | list) -> list[str]:
    """Walk an Atlassian Document Format tree and collect text content."""
    texts: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "text":
            texts.append(node.get("text", ""))
        for child in node.get("content", []):
            texts.extend(_extract_adf_text(child))
    elif isinstance(node, list):
        for item in node:
            texts.extend(_extract_adf_text(item))
    return texts


def extract_components_from_ticket(
    labels: list[str],
    description: str | dict | None,
) -> list[str]:
    """Extract Konflux component / container image names from a Jira ticket.

    Sources (in order):
      1. Exception labels: ``Exception-<rule>:<component>``
      2. Description text: ``odh-*-rhel9`` / ``quay.io/rhoai/<name>`` patterns

    Handles both ADF (dict) and wiki-markup (str) description formats.
    Returns a sorted, deduplicated list.
    """
    names: set[str] = set()

    for label in labels or []:
        m = _EXCEPTION_LABEL_RE.match(label)
        if m:
            names.add(m.group(2).strip())

    desc_text = ""
    if isinstance(description, dict):
        desc_text = " ".join(_extract_adf_text(description))
    elif isinstance(description, str):
        desc_text = description

    if desc_text:
        names.update(_IMAGE_NAME_RE.findall(desc_text))
        names.update(_QUAY_IMAGE_RE.findall(desc_text))

    return sorted(names)


def audit_jira_components(
    catalog: list[dict],
    jql: str = 'project = RHOAIENG AND labels = "conforma-exception-ai-skill"',
    *,
    fix: bool = False,
) -> list[dict]:
    """Audit and optionally fix Jira Component fields on RHOAIENG tickets.

    Searches Jira for tickets matching ``jql``, extracts Konflux component
    names from labels/descriptions, resolves them to Jira Components via the
    catalog, and returns a list of proposed changes.

    When ``fix=True``, also updates tickets via the Jira REST API.

    Returns a list of per-ticket dicts::

        {
            "key": "RHOAIENG-12345",
            "summary": "...",
            "current_components": ["DevOps"],
            "extracted_names": ["odh-vllm-gaudi-rhel9"],
            "resolved_components": ["Model Runtimes"],
            "needs_update": true,
            "updated": false,
        }
    """
    import jira_ops

    client = jira_ops.get_client()
    issues = client.search_issues(jql, maxResults=200, fields="summary,components,labels,description")
    index = _build_lookup_index(catalog)
    results: list[dict] = []

    for issue in issues:
        current = [c.name for c in issue.fields.components] if issue.fields.components else []
        labels = issue.fields.labels or []
        desc = issue.fields.description

        extracted = extract_components_from_ticket(labels, desc)
        resolved_map = {n: _resolve_single(n, index) for n in extracted}
        resolved_comps = sorted(set(v for v in resolved_map.values() if v))
        unmapped = sorted(k for k, v in resolved_map.items() if v is None)

        merged = sorted(set(current) | set(resolved_comps)) if resolved_comps else current
        needs_update = bool(resolved_comps) and set(merged) != set(current)

        entry: dict = {
            "key": issue.key,
            "summary": issue.fields.summary[:80],
            "current_components": current,
            "extracted_names": extracted,
            "resolved_components": resolved_comps,
            "unmapped_names": unmapped,
            "needs_update": needs_update,
            "updated": False,
        }

        if fix and needs_update and resolved_comps:
            ok = _apply_jira_components_rest(issue.key, merged)
            entry["updated"] = ok
            entry["final_components"] = merged if ok else current

        results.append(entry)

    return results


def _apply_jira_components_rest(ticket_key: str, components: list[str]) -> bool:
    """Set Jira Components on a ticket via REST API. Returns True on success."""
    import requests

    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not email or not token:
        return False

    url = f"https://redhat.atlassian.net/rest/api/2/issue/{ticket_key}"
    payload = {"fields": {"components": [{"name": c} for c in components]}}
    resp = requests.put(url, json=payload, auth=(email, token), timeout=20)
    return resp.status_code == 204


def main() -> int:
    parser = argparse.ArgumentParser(description="Component catalog primitives")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("ensure-repo", help="Clone or update the component-maturity repo")

    resolve_parser = sub.add_parser("resolve", help="Resolve Konflux names to Jira Components")
    resolve_group = resolve_parser.add_mutually_exclusive_group(required=True)
    resolve_group.add_argument("--component", help="Single Konflux component name")
    resolve_group.add_argument("--components", help="Comma-separated Konflux component names")

    sub.add_parser("list", help="List all mapped components and their Jira components")

    audit_parser = sub.add_parser(
        "audit-jira-components",
        help="Audit Jira Component fields on RHOAIENG conforma tickets",
    )
    audit_parser.add_argument(
        "--jql",
        default='project = RHOAIENG AND labels = "conforma-exception-ai-skill"',
        help="JQL query to find tickets (default: conforma-exception-ai-skill labeled RHOAIENG tickets)",
    )
    audit_parser.add_argument(
        "--fix",
        action="store_true",
        help="Update Jira tickets with resolved components (without this flag, only prints what would change)",
    )

    args = parser.parse_args()

    if args.command == "ensure-repo":
        result = ensure_catalog_repo()
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    elif args.command == "resolve":
        catalog = load_catalog()
        names = [args.component] if args.component else [c.strip() for c in args.components.split(",")]
        resolved = resolve_jira_components(names, catalog)
        print(json.dumps(resolved, indent=2))
        unmapped = [k for k, v in resolved.items() if v is None]
        return 1 if unmapped else 0

    elif args.command == "list":
        catalog = load_catalog()
        index = _build_lookup_index(catalog)
        by_component: dict[str, list[str]] = {}
        for name, jira_comp in sorted(index.items()):
            by_component.setdefault(jira_comp, []).append(name)
        for jira_comp in sorted(by_component):
            print(f"\n{jira_comp}:")
            for name in sorted(by_component[jira_comp]):
                print(f"  {name}")
        return 0

    elif args.command == "audit-jira-components":
        catalog = load_catalog()
        results = audit_jira_components(catalog, jql=args.jql, fix=args.fix)
        print(json.dumps(results, indent=2))
        needs_update = [r for r in results if r["needs_update"]]
        if needs_update and not args.fix:
            print(
                f"\n{len(needs_update)} ticket(s) need updates. Re-run with --fix to update them.",
                file=sys.stderr,
            )
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
