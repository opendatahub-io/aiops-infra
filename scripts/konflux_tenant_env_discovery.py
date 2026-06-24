"""Konflux tenant environment discovery (dual-mode: CLI + importable).

Given a tenant name, discovers the user's Konflux and Conforma environment:
clusters, Conforma policy files, RPA directories, and self-service exception paths
from the konflux-release-data GitLab repository using the Tree API.

This is the primary method for configuring aiops-infra infrastructure.
Users only need to provide GITLAB_HOST and TENANT — everything else
(cluster domain, API URLs, policy paths) is auto-discovered.

Exit codes:
    0  — discovery succeeded (JSON on stdout)
    1  — general/unexpected error
    8  — tenant not found in any cluster
    9  — GitLab API error (network, auth, rate limit)
    10 — multiple clusters found, user must set preferred_cluster

Usage as library:
    import konflux_tenant_env_discovery
    ctx = konflux_tenant_env_discovery.discover("my-tenant", preferred_cluster="my-cluster-id")

Usage as CLI:
    python3 scripts/konflux_tenant_env_discovery.py --tenant my-tenant
    python3 scripts/konflux_tenant_env_discovery.py --tenant my-tenant --preferred-cluster my-cluster-id
    python3 scripts/konflux_tenant_env_discovery.py --tenant rhoai-tenant --refresh
    python3 scripts/konflux_tenant_env_discovery.py --tenant rhoai-tenant --export
    python3 scripts/konflux_tenant_env_discovery.py --tenant rhoai-tenant --human
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DISCOVERY_CACHE_DIR = Path.home() / ".config" / "aiops-infra" / ".discovery-cache"
DISCOVERY_CACHE_TTL_HOURS = 72


@dataclass
class DiscoveredCluster:
    cluster_id: str
    cluster_domain: str


@dataclass
class TenantContext:
    tenant: str
    cluster: DiscoveredCluster
    all_clusters: list[DiscoveredCluster]
    conforma_policy_dir: str
    conforma_policy_files: list[str]
    rpa_dir: str
    rpa_subdirs: list[str]
    self_service_dir: str
    self_service_files: list[str]
    discovered_at: str
    source_commit: str
    preferred_cluster: str | None


class DiscoveryError(Exception):
    """Raised when discovery fails with a specific exit code."""

    def __init__(self, message: str, exit_code: int):
        super().__init__(message)
        self.exit_code = exit_code


def _get_gitlab_project():
    """Get an authenticated python-gitlab project object."""
    import gitlab as gitlab_mod

    host = os.environ.get("GITLAB_HOST", "")
    project_path = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")

    try:
        import gitlab_ops
        token = gitlab_ops.discover_token(f"https://{host}")
    except Exception:
        token = os.environ.get("GITLAB_TOKEN")

    if not token:
        raise DiscoveryError(
            f"No GitLab token found for {host}. Set GITLAB_TOKEN or run: glab auth login --hostname {host}",
            exit_code=9,
        )

    ssl_verify = os.environ.get("GITLAB_SSL_VERIFY", "true").lower() not in ("false", "0", "no")

    try:
        gl = gitlab_mod.Gitlab(url=f"https://{host}", private_token=token, ssl_verify=ssl_verify, timeout=15)
        gl.auth()
        project = gl.projects.get(project_path)
        return project
    except Exception as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc) and ssl_verify:
            try:
                gl = gitlab_mod.Gitlab(url=f"https://{host}", private_token=token, ssl_verify=False, timeout=15)
                gl.auth()
                project = gl.projects.get(project_path)
                return project
            except Exception as inner_exc:
                raise DiscoveryError(f"GitLab API error: {inner_exc}", exit_code=9) from inner_exc
        raise DiscoveryError(f"GitLab API error: {exc}", exit_code=9) from exc


def _list_tree(project, path: str) -> list[dict]:
    """List all items at a path using GitLab Tree API with pagination."""
    items = []
    try:
        page = 1
        while True:
            batch = project.repository_tree(path=path, per_page=100, page=page, ref="main")
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    except Exception as exc:
        raise DiscoveryError(f"GitLab Tree API error listing '{path}': {exc}", exit_code=9) from exc
    return items


def _get_head_sha(project) -> str:
    """Get HEAD commit SHA of main branch."""
    try:
        commits = project.commits.list(ref_name="main", per_page=1)
        return commits[0].id if commits else ""
    except Exception:
        return ""


def _read_cache(tenant: str, preferred_cluster: str | None) -> TenantContext | None:
    """Read cached discovery result if fresh and matching."""
    cache_file = DISCOVERY_CACHE_DIR / f"{tenant}.json"
    if not cache_file.is_file():
        return None

    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    discovered_at = data.get("discovered_at", "")
    try:
        dt = datetime.fromisoformat(discovered_at)
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if age_hours >= DISCOVERY_CACHE_TTL_HOURS:
            return None
    except (ValueError, TypeError):
        return None

    if data.get("preferred_cluster") != preferred_cluster:
        return None

    try:
        cluster = DiscoveredCluster(**data["cluster"])
        all_clusters = [DiscoveredCluster(**c) for c in data["all_clusters"]]
        return TenantContext(
            tenant=data["tenant"],
            cluster=cluster,
            all_clusters=all_clusters,
            conforma_policy_dir=data["conforma_policy_dir"],
            conforma_policy_files=data["conforma_policy_files"],
            rpa_dir=data["rpa_dir"],
            rpa_subdirs=data["rpa_subdirs"],
            self_service_dir=data["self_service_dir"],
            self_service_files=data["self_service_files"],
            discovered_at=data["discovered_at"],
            source_commit=data["source_commit"],
            preferred_cluster=data.get("preferred_cluster"),
        )
    except (KeyError, TypeError):
        return None


def _write_cache(ctx: TenantContext) -> None:
    """Write discovery result to cache."""
    DISCOVERY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = DISCOVERY_CACHE_DIR / f"{ctx.tenant}.json"
    cache_file.write_text(json.dumps(asdict(ctx), indent=2), encoding="utf-8")


def discover(
    tenant: str,
    preferred_cluster: str | None = None,
    refresh: bool = False,
) -> TenantContext:
    """Run Konflux tenant environment discovery against konflux-release-data via GitLab Tree API.

    Args:
        tenant: Tenant name (e.g. "rhoai-tenant")
        preferred_cluster: Cluster ID to select when multiple match
        refresh: If True, ignore cache

    Returns:
        TenantContext with all discovered data

    Raises:
        DiscoveryError with appropriate exit_code on failure
    """
    if not refresh:
        cached = _read_cache(tenant, preferred_cluster)
        if cached is not None:
            return cached

    project = _get_gitlab_project()

    # Step 2: List all cluster IDs
    cluster_dirs = _list_tree(project, "tenants-config/cluster")
    cluster_ids = [item["name"] for item in cluster_dirs if item.get("type") == "tree"]

    # Step 3: Find which clusters have our tenant
    matching_cluster_ids: list[str] = []
    for cid in cluster_ids:
        tenant_dirs = _list_tree(project, f"tenants-config/cluster/{cid}/tenants")
        tenant_names = [item["name"] for item in tenant_dirs if item.get("type") == "tree"]
        if tenant in tenant_names:
            matching_cluster_ids.append(cid)

    # Step 4: Tenant not found
    if not matching_cluster_ids:
        raise DiscoveryError(
            f"Tenant '{tenant}' not found in any cluster. "
            f"Searched {len(cluster_ids)} cluster(s): {', '.join(sorted(cluster_ids)[:10])}...",
            exit_code=8,
        )

    # Step 5: Resolve cluster IDs to full domain names
    config_dirs = _list_tree(project, "config")
    domain_names = [item["name"] for item in config_dirs if item.get("type") == "tree"]

    discovered_clusters: list[DiscoveredCluster] = []
    for cid in matching_cluster_ids:
        for domain in domain_names:
            if domain.split(".")[0] == cid:
                discovered_clusters.append(DiscoveredCluster(cluster_id=cid, cluster_domain=domain))
                break

    if not discovered_clusters:
        raise DiscoveryError(
            f"Found tenant '{tenant}' in cluster(s) {matching_cluster_ids}, "
            f"but no matching config/ domain directory found.",
            exit_code=9,
        )

    # Step 6: Select cluster
    if preferred_cluster:
        selected = [c for c in discovered_clusters if c.cluster_id == preferred_cluster]
        if not selected:
            available = ", ".join(c.cluster_id for c in discovered_clusters)
            raise DiscoveryError(
                f"preferred_cluster '{preferred_cluster}' not found among discovered clusters.\n"
                f"Available clusters for tenant '{tenant}': {available}",
                exit_code=10,
            )
        selected_cluster = selected[0]
    elif len(discovered_clusters) == 1:
        selected_cluster = discovered_clusters[0]
    else:
        available = ", ".join(c.cluster_id for c in discovered_clusters)
        raise DiscoveryError(
            f"Tenant '{tenant}' exists on multiple clusters: {available}\n"
            f"Set PREFERRED_KONFLUX_CLUSTER in .work/.env or pass --preferred-cluster.",
            exit_code=10,
        )

    # Step 7a: List EnterpriseContractPolicy files
    conforma_policy_dir = f"config/{selected_cluster.cluster_domain}/product/EnterpriseContractPolicy"
    try:
        conforma_items = _list_tree(project, conforma_policy_dir)
        conforma_policy_files = sorted(
            item["name"] for item in conforma_items if item.get("type") == "blob" and item["name"].endswith(".yaml")
        )
    except DiscoveryError:
        conforma_policy_files = []

    # Step 7b: List ReleasePlanAdmission subdirectories
    rpa_dir = f"config/{selected_cluster.cluster_domain}/product/ReleasePlanAdmission"
    try:
        rpa_items = _list_tree(project, rpa_dir)
        rpa_subdirs = sorted(item["name"] for item in rpa_items if item.get("type") == "tree")
    except DiscoveryError:
        rpa_subdirs = []

    # Step 7c: List self-service exception files
    self_service_dir = "exceptions"
    try:
        exc_items = _list_tree(project, self_service_dir)
        self_service_files = sorted(
            item["name"] for item in exc_items if item.get("type") == "blob" and item["name"].endswith(".yaml")
        )
    except DiscoveryError:
        self_service_files = []

    # Step 8: Record HEAD SHA
    source_commit = _get_head_sha(project)

    # Step 9: Assemble and cache
    ctx = TenantContext(
        tenant=tenant,
        cluster=selected_cluster,
        all_clusters=discovered_clusters,
        conforma_policy_dir=conforma_policy_dir,
        conforma_policy_files=conforma_policy_files,
        rpa_dir=rpa_dir,
        rpa_subdirs=rpa_subdirs,
        self_service_dir=self_service_dir,
        self_service_files=self_service_files,
        discovered_at=datetime.now(timezone.utc).isoformat(),
        source_commit=source_commit,
        preferred_cluster=preferred_cluster,
    )

    _write_cache(ctx)
    return ctx


def main() -> int:
    parser = argparse.ArgumentParser(description="Tenant-based auto-discovery for Konflux release infrastructure")
    parser.add_argument("--tenant", required=True, help="Tenant name (e.g. rhoai-tenant)")
    parser.add_argument("--preferred-cluster", default=None, help="Cluster ID to select when multiple match")
    parser.add_argument("--refresh", action="store_true", help="Ignore cache, force fresh discovery")
    parser.add_argument("--export", action="store_true", help="Output as shell export statements")
    parser.add_argument("--human", action="store_true", help="Output as human-readable table")
    parser.add_argument("--json", action="store_true", help="Output as JSON (default)")
    args = parser.parse_args()

    try:
        import konflux_environment
        konflux_environment.load()
    except Exception:
        pass

    try:
        ctx = discover(args.tenant, preferred_cluster=args.preferred_cluster, refresh=args.refresh)
    except DiscoveryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code

    if args.export:
        print(f'export KONFLUX_CLUSTER_DOMAIN="{ctx.cluster.cluster_domain}"')
        print(f'export KONFLUX_CONFORMA_POLICY_DIR="{ctx.conforma_policy_dir}"')
        print(f'export KONFLUX_RPA_SUBPATH="{ctx.rpa_dir}"')
        if ctx.rpa_subdirs:
            print(f'export KONFLUX_RPA_SUBPATH="{ctx.rpa_dir}/{ctx.rpa_subdirs[0]}"')
        return 0

    if args.human:
        print(f"Tenant:           {ctx.tenant}")
        print(f"Selected cluster: {ctx.cluster.cluster_id} ({ctx.cluster.cluster_domain})")
        print(f"All clusters:     {', '.join(c.cluster_id for c in ctx.all_clusters)}")
        print(f"Conforma policy dir:    {ctx.conforma_policy_dir}")
        print(f"Conforma policy files:  {', '.join(ctx.conforma_policy_files) or '(none)'}")
        print(f"RPA dir:          {ctx.rpa_dir}")
        print(f"RPA products:     {', '.join(ctx.rpa_subdirs) or '(none)'}")
        print(f"Self-service dir: {ctx.self_service_dir}")
        print(f"Self-service:     {', '.join(ctx.self_service_files) or '(none)'}")
        print(f"Discovered at:    {ctx.discovered_at}")
        print(f"Source commit:    {ctx.source_commit[:12] if ctx.source_commit else '(unknown)'}")
        return 0

    print(json.dumps(asdict(ctx), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
