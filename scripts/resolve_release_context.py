#!/usr/bin/env python3
"""Resolve a user's release query into a validated Konflux application context.

Queries the konflux-release-data GitLab tree for actual version directories,
matches against the user's input, and outputs a JSON result with full
environment context for confirmation before proceeding with a conforma workflow.

Usage:
    python3 scripts/resolve_release_context.py --query "rhoai-3.5-ea.1"
    python3 scripts/resolve_release_context.py --query "3.4"
    python3 scripts/resolve_release_context.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

import gitlab_ops
import konflux_environment


# ---------------------------------------------------------------------------
# Pure derivation functions
# ---------------------------------------------------------------------------


def version_to_release(version_dir: str) -> str:
    """Derive conforma-reporter branch from version directory name.

    v3.5-ea.1 -> rhoai-3.5-ea.1
    v3.4      -> rhoai-3.4
    """
    return "rhoai-" + version_dir.lstrip("v")


def version_to_konflux_app(version_dir: str) -> str:
    """Derive Konflux Application name from version directory name.

    v3.5-ea.1 -> rhoai-v3-5-ea-1
    v3.4      -> rhoai-v3-4
    """
    return "rhoai-" + version_dir.replace(".", "-")


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------


def parse_query(raw: str) -> str | None:
    """Normalize user input into a candidate version directory name.

    Returns the candidate (e.g. "v3.5-ea.1") or None if parsing fails.
    """
    text = raw.strip().lower()
    if not text:
        return None

    # Strip leading "rhoai" with optional separator
    text = re.sub(r"^rhoai[\s\-]*", "", text)

    # Strip leading "v" if present
    text = re.sub(r"^v", "", text)

    # Normalize EA patterns:
    #   "3.5 ea 1"   -> "3.5-ea.1"
    #   "3.5-ea-1"   -> "3.5-ea.1"
    #   "3.5-ea.1"   -> "3.5-ea.1" (already correct)
    #   "3.5.ea.1"   -> "3.5-ea.1"
    ea_match = re.match(
        r"^(\d+\.\d+)[\s.\-]+ea[\s.\-]+(\d+)$", text
    )
    if ea_match:
        text = f"{ea_match.group(1)}-ea.{ea_match.group(2)}"

    # Validate: must be X.Y or X.Y-ea.N
    if not re.match(r"^\d+\.\d+(-ea\.\d+)?$", text):
        return None

    return f"v{text}"


# ---------------------------------------------------------------------------
# GitLab discovery
# ---------------------------------------------------------------------------


def list_version_dirs(cluster_id: str, tenant: str) -> list[str]:
    """List version directories from the konflux-release-data GitLab tree."""
    gl = gitlab_ops.get_client()
    project_path = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")
    project = gl.projects.get(project_path)
    tree_path = f"tenants-config/cluster/{cluster_id}/tenants/{tenant}"

    items: list[dict] = []
    page = 1
    while True:
        batch = project.repository_tree(path=tree_path, per_page=100, page=page, ref="main")
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    return sorted(
        item["name"] for item in items
        if item.get("type") == "tree" and re.match(r"^v\d", item["name"])
    )


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------


def match_versions(candidate: str, available: list[str]) -> list[str]:
    """Match a candidate against available version directories.

    Returns list of matches. Exact match takes priority; if no exact match,
    returns all prefix matches.
    """
    if candidate in available:
        return [candidate]

    prefix_matches = [v for v in available if v.startswith(candidate)]
    return prefix_matches


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _build_links(
    cluster_domain: str,
    policy_dir: str,
    gitlab_host: str,
    gitlab_project: str,
    policy_files: list[str],
    app_slug: str,
) -> dict:
    """Build clickable URLs for cluster, policy dir, and policy files."""
    links: dict[str, str | list[dict[str, str]]] = {}
    if cluster_domain:
        links["cluster_console"] = f"https://console-openshift-console.apps.{cluster_domain}/"
    if gitlab_host and policy_dir:
        links["policy_dir"] = (
            f"https://{gitlab_host}/{gitlab_project}/-/tree/main/{policy_dir}"
        )
        relevant = [f for f in policy_files if app_slug and app_slug in f]
        if relevant:
            links["policy_files"] = [
                {
                    "name": f,
                    "url": f"https://{gitlab_host}/{gitlab_project}/-/blob/main/{policy_dir}/{f}",
                }
                for f in sorted(relevant)
            ]
    return links


def _format_resolved(
    query: str,
    version_dir: str,
    cluster_domain: str,
    tenant: str,
    policy_dir: str,
    links: dict | None = None,
) -> str:
    release = version_to_release(version_dir)
    app = version_to_konflux_app(version_dir)

    cluster_text = cluster_domain
    if links and links.get("cluster_console"):
        cluster_text = f"[{cluster_domain}]({links['cluster_console']})"

    policy_dir_text = policy_dir
    if links and links.get("policy_dir"):
        policy_dir_text = f"[{policy_dir}]({links['policy_dir']})"

    policy_file_links = []
    if links and links.get("policy_files"):
        policy_file_links = [f"[{f['name']}]({f['url']})" for f in links["policy_files"]]

    lines = [
        "### Conforma Workflow \u2014 Context Confirmation",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| **User requested** | {query} |",
        f"| **Release branch** | {release} |",
        f"| **Konflux Application** | {app} |",
        f"| **Cluster domain** | {cluster_text} |",
        f"| **Tenant** | {tenant} |",
        f"| **Conforma policy dir** | {policy_dir_text} |",
        f"| **Environment** | prod |",
    ]
    if policy_file_links:
        files_cell = "<br>".join(f"• {link}" for link in policy_file_links)
        lines.append(f"| **Policy files** | {files_cell} |")
    lines.extend([
        "",
        "*Source: GitLab tree (konflux-release-data, main branch)*",
    ])
    return "\n".join(lines)


def _format_ambiguous(query: str, candidates: list[str]) -> str:
    lines = [
        "### Conforma Workflow \u2014 Multiple Matches",
        "",
        f'User requested: **{query}**',
        "",
        "| # | Version | Release | Application |",
        "|---|---------|---------|-------------|",
    ]
    for i, v in enumerate(candidates, 1):
        release = version_to_release(v)
        app = version_to_konflux_app(v)
        lines.append(f"| {i} | {v} | {release} | {app} |")
    lines.extend(["", "Please select which version to use."])
    return "\n".join(lines)


def _format_not_found(query: str, available: list[str], tenant: str, cluster_id: str) -> str:
    lines = [
        "### Conforma Workflow \u2014 Version Not Found",
        "",
        f'User requested: **{query}**',
        "",
        f'No matching version found in tenant `{tenant}` on cluster `{cluster_id}`.',
        "",
        "**Available versions:**",
        "",
        "| Version | Release | Application |",
        "|---------|---------|-------------|",
    ]
    for v in available:
        release = version_to_release(v)
        app = version_to_konflux_app(v)
        lines.append(f"| {v} | {release} | {app} |")
    return "\n".join(lines)


def _format_error(messages: list[str]) -> str:
    lines = [
        "### Conforma Workflow \u2014 Context Resolution Failed",
        "",
    ]
    for msg in messages:
        lines.append(msg)
    lines.extend([
        "",
        "Run prerequisites check first:",
        "",
        "```",
        "python3 scripts/verify_conforma_prerequisites.py --fix",
        "```",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main resolution logic
# ---------------------------------------------------------------------------


def resolve(query: str) -> dict:
    """Resolve a user query into full release context. Returns JSON-serializable dict."""
    konflux_environment.load()

    cluster_domain = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
    tenant = os.environ.get("KONFLUX_TENANT") or os.environ.get("KONFLUX_NAMESPACE", "")
    policy_dir = os.environ.get("KONFLUX_CONFORMA_POLICY_DIR", "not discovered")

    missing = []
    if not cluster_domain:
        missing.append("KONFLUX_CLUSTER_DOMAIN (not set)")
    if not tenant:
        missing.append("TENANT or KONFLUX_NAMESPACE (not set)")

    if missing:
        display = _format_error([f"Missing required environment:"] + [f"  - {m}" for m in missing])
        return {"status": "error", "confirmation_display": display}

    cluster_id = cluster_domain.split(".")[0]

    candidate = parse_query(query)
    if candidate is None:
        display = _format_error([
            f'Could not parse release from query: "{query}"',
            "",
            "Expected formats: rhoai-X.Y, X.Y, X.Y-ea.N, rhoai-X.Y-ea.N",
        ])
        return {"status": "error", "confirmation_display": display}

    try:
        available = list_version_dirs(cluster_id, tenant)
    except Exception as exc:
        display = _format_error([
            f"GitLab tree query failed: {exc}",
            "",
            "Check GITLAB_HOST, GITLAB_TOKEN, and GITLAB_PROJECT in .work/.env",
        ])
        return {"status": "error", "confirmation_display": display}

    matches = match_versions(candidate, available)

    if len(matches) == 1:
        v = matches[0]
        gitlab_host = os.environ.get("GITLAB_HOST", "")
        gitlab_project = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")
        policy_files_raw = os.environ.get("KONFLUX_CONFORMA_POLICY_FILES", "")
        policy_files = [f.strip() for f in policy_files_raw.split(",") if f.strip()]
        app_slug = "rhoai"
        links = _build_links(
            cluster_domain, policy_dir, gitlab_host, gitlab_project, policy_files, app_slug,
        )
        display = _format_resolved(query, v, cluster_domain, tenant, policy_dir, links)
        return {
            "status": "resolved",
            "release": version_to_release(v),
            "konflux_app": version_to_konflux_app(v),
            "version_dir": v,
            "cluster_domain": cluster_domain,
            "cluster_id": cluster_id,
            "tenant": tenant,
            "conforma_policy_dir": policy_dir,
            "environment": "prod",
            "available_versions": available,
            "links": links,
            "confirmation_display": display,
        }

    if len(matches) > 1:
        display = _format_ambiguous(query, matches)
        candidates = [
            {
                "version_dir": v,
                "release": version_to_release(v),
                "konflux_app": version_to_konflux_app(v),
            }
            for v in matches
        ]
        return {
            "status": "ambiguous",
            "candidates": candidates,
            "available_versions": available,
            "confirmation_display": display,
        }

    # No match
    display = _format_not_found(query, available, tenant, cluster_id)
    return {
        "status": "not_found",
        "available_versions": available,
        "confirmation_display": display,
    }


def list_all() -> dict:
    """List all available versions without matching."""
    konflux_environment.load()

    cluster_domain = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
    tenant = os.environ.get("KONFLUX_TENANT") or os.environ.get("KONFLUX_NAMESPACE", "")

    missing = []
    if not cluster_domain:
        missing.append("KONFLUX_CLUSTER_DOMAIN (not set)")
    if not tenant:
        missing.append("KONFLUX_TENANT (not set)")

    if missing:
        display = _format_error(["Missing required environment:"] + [f"  - {m}" for m in missing])
        return {"status": "error", "confirmation_display": display}

    cluster_id = cluster_domain.split(".")[0]

    try:
        available = list_version_dirs(cluster_id, tenant)
    except Exception as exc:
        display = _format_error([f"GitLab tree query failed: {exc}"])
        return {"status": "error", "confirmation_display": display}

    lines = [
        "### Conforma Workflow \u2014 Available Versions",
        "",
        f"**Tenant:** {tenant} | **Cluster:** {cluster_id}",
        "",
        "| Version | Release | Application |",
        "|---------|---------|-------------|",
    ]
    for v in available:
        release = version_to_release(v)
        app = version_to_konflux_app(v)
        lines.append(f"| {v} | {release} | {app} |")

    return {
        "status": "list",
        "available_versions": available,
        "versions": [
            {
                "version_dir": v,
                "release": version_to_release(v),
                "konflux_app": version_to_konflux_app(v),
            }
            for v in available
        ],
        "confirmation_display": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a release query into Konflux application context."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", help="Release identifier from user (e.g. 'rhoai-3.5-ea.1', '3.4')")
    group.add_argument("--list", action="store_true", help="List all available versions")
    args = parser.parse_args()

    if args.list:
        result = list_all()
    else:
        result = resolve(args.query)

    json.dump(result, sys.stdout, indent=2)
    print()

    if result["status"] in ("error", "not_found"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
