"""conforma_mr_ops.py -- Conforma Merge Request discovery primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import gitlab_ops

GITLAB_HOST = os.environ.get("GITLAB_HOST", "")
GITLAB_PROJECT = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")

EXCEPTION_PATH_MARKERS = ("EnterpriseContractPolicy/", "exceptions/")
"""File-path substrings that identify conforma registry (exception/policy)
files.  A Merge Request whose diff touches any path matching these markers
is classified as an **exception** Merge Request; all others are **remedy**."""

_thread_local = threading.local()


def _ensure_gitlab_env() -> None:
    """Bridge conforma token discovery to env vars for gitlab_ops."""
    if not os.environ.get("GITLAB_TOKEN"):
        token = gitlab_ops.discover_token()
        if token:
            os.environ["GITLAB_TOKEN"] = token


def _get_project():
    """Return a per-thread cached GitLab project handle.

    Each thread gets its own ``gitlab.Gitlab`` client (``requests.Session``
    is not thread-safe) but authenticates only once per thread lifetime.
    """
    if not hasattr(_thread_local, "project") or _thread_local.project is None:
        _ensure_gitlab_env()
        gl = gitlab_ops.get_client(instance_url=GITLAB_HOST)
        _thread_local.project = gl.projects.get(GITLAB_PROJECT)
    return _thread_local.project


def _extract_image_base(image_url: str) -> str:
    """Extract the base image name from a full imageUrl.

    quay.io/rhoai/odh-dashboard-rhel9 -> odh-dashboard
    quay.io/rhoai/odh-mlmd-grpc-server-rhel9 -> odh-mlmd-grpc-server
    quay.io/rhoai/odh-vllm-cpu-rhel9 -> odh-vllm-cpu
    """
    name = image_url.rsplit("/", 1)[-1]
    name = re.sub(r"-rhel\d+$", "", name)
    name = re.sub(r"-ubi\d+$", "", name)
    return name


def _extract_component_base(component_name: str) -> str:
    """Extract the base name from a Konflux componentName (strip version suffix).

    odh-dashboard-v3-4 -> odh-dashboard
    odh-mlmd-grpc-server-v2-25 -> odh-mlmd-grpc-server
    odh-vllm-cpu-v3-5-ea-1 -> odh-vllm-cpu
    """
    return re.sub(r"-v\d+-\d+(?:-[a-z]+-\d+)?$", "", component_name)


def image_url_covers_component(image_url: str, component_name: str) -> bool:
    """Check if an imageUrl-scoped exception covers a given componentName.

    An imageUrl like quay.io/rhoai/odh-dashboard-rhel9 covers all components
    with base name odh-dashboard (e.g. odh-dashboard-v3-3, odh-dashboard-v3-4).
    """
    return _extract_image_base(image_url) == _extract_component_base(component_name)


def classify_mr_type(changes: list[dict]) -> str:
    """Classify a Merge Request as ``exception`` or ``remedy`` from its diff.

    Deterministic rule — based solely on changed file paths:

    - ``exception``: at least one changed file matches
      :data:`EXCEPTION_PATH_MARKERS` (conforma registry / policy files).
    - ``remedy``: no changed files match those markers (component fix,
      build-config change, or any other non-exception change).
    """
    for change in changes:
        path = change.get("new_path", "")
        if any(marker in path for marker in EXCEPTION_PATH_MARKERS):
            return "exception"
    return "remedy"


def _glab_get_mrs(search_term: str, timeout: int = 15) -> list[dict]:
    """List open Merge Requests matching a search term via python-gitlab."""
    try:
        project = _get_project()
        mrs = project.mergerequests.list(
            state="opened",
            search=search_term,
            per_page=20,
            get_all=False,
            timeout=timeout,
        )
        return [
            {
                "iid": mr.iid,
                "title": mr.title,
                "description": mr.description or "",
                "web_url": mr.web_url,
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
                "state": mr.state,
                "author": getattr(mr.author, "username", "") if hasattr(mr, "author") and mr.author else "",
            }
            for mr in mrs
        ]
    except Exception:
        return []


def search_open_exception_mrs(rule: str) -> list[dict]:
    """Search for open Merge Requests in konflux-release-data that mention this rule.

    Performs two searches and merges results:
    1. Full rule string (e.g. ``rpm_signature.allowed:9386b48a1a693c5c``)
    2. Suffix after the last ``:`` (e.g. ``9386b48a1a693c5c``) as a safety net
       in case GitLab tokenises on colons

    Results are deduplicated by ``iid``.
    """
    search_term = rule
    if len(search_term) > 60:
        search_term = search_term[:60]

    raw_mrs = _glab_get_mrs(search_term)

    if ":" in rule:
        suffix = rule.rsplit(":", 1)[1]
        if suffix and suffix != search_term:
            raw_mrs.extend(_glab_get_mrs(suffix))

    seen_iids: set[int] = set()
    results: list[dict] = []
    for mr in raw_mrs:
        iid = mr.get("iid")
        if iid in seen_iids:
            continue
        seen_iids.add(iid)
        author_val = mr.get("author")
        author_name = author_val.get("username", "") if isinstance(author_val, dict) else str(author_val or "")
        results.append(
            {
                "iid": iid,
                "title": mr.get("title", ""),
                "url": mr.get("web_url", ""),
                "author": author_name,
                "created_at": mr.get("created_at", ""),
                "description": mr.get("description", ""),
            }
        )

    return results


GLOBAL_COVERAGE: list[str] = ["*"]
"""Sentinel returned by ``_parse_components_from_diff`` when the rule is added
without component scoping (permanent exclusion or global volatile exception).
Callers must check ``"*" in result`` before computing set intersections."""


def _parse_diff_lines(diff_text: str) -> list[tuple[str, bool]]:
    """Parse a unified diff into ``(stripped_content, is_added)`` tuples.

    Skips diff headers (``@@``, ``---``, ``+++``) and removed lines.
    Context lines (space-prefixed) are included with ``is_added=False``
    so callers can inspect the surrounding YAML structure.
    """
    result: list[tuple[str, bool]] = []
    for raw in diff_text.splitlines():
        if raw.startswith(("@@", "---", "+++")):
            continue
        if raw.startswith("-"):
            continue
        is_added = raw.startswith("+")
        content = raw[1:] if raw and raw[0] in ("+", " ") else raw
        result.append((content.strip(), is_added))
    return result


def _parse_components_from_diff(diff_text: str, rule: str) -> list[str]:
    """Extract componentNames for a given rule from a unified diff.

    Processes both added (``+``) and context (`` ``) lines to correctly
    detect component scoping even when ``componentNames:`` / ``imageUrl:``
    are pre-existing context rather than new additions.

    **Permanent exclusion** — bare ``- <rule>`` on an added line.  These
    appear only in ``config.exclude`` (not ``volatileConfig``), which uses
    the simple list format.  Structurally distinct from ``volatileConfig``
    entries which always use ``- value: <rule>``.

    **Global volatile exception** — ``- value: <rule>`` on an added line
    with no ``componentNames:`` or ``imageUrl:`` among its sibling keys
    (whether added or context).

    Returns:
      - Specific component names when ``componentNames:`` is present.
      - :data:`GLOBAL_COVERAGE` (``["*"]``) when the rule is added without
        component scoping.
      - Empty list when the rule is not found in added lines.
    """
    lines = _parse_diff_lines(diff_text)

    # --- Permanent exclusion: bare "- <rule>" on an added line ---
    # config.exclude uses bare list items; volatileConfig uses "- value:" —
    # these formats are structurally distinct in the policy schema.
    for stripped, is_added in lines:
        if is_added and (stripped == f"- {rule}" or stripped == f'- "{rule}"'):
            return GLOBAL_COVERAGE

    # --- Volatile exception: "- value: <rule>" on an added line ---
    # Scan ALL subsequent lines (context included) for componentNames/imageUrl
    # because the scoping keys may be pre-existing (unchanged) context.
    components: list[str] = []
    i = 0
    while i < len(lines):
        stripped, is_added = lines[i]
        if is_added and (stripped == f"- value: {rule}" or stripped == f'- value: "{rule}"'):
            i += 1
            in_component_names = False
            has_component_scoping = False
            while i < len(lines):
                s, _ = lines[i]
                if not s or s.startswith("- value:"):
                    break
                if s.startswith("componentNames:") or s.startswith("imageUrl:"):
                    has_component_scoping = True
                if s == "componentNames:":
                    in_component_names = True
                    i += 1
                    continue
                if in_component_names and s.startswith("- "):
                    comp = s[2:].strip().strip('"').strip("'")
                    if comp:
                        components.append(comp)
                    i += 1
                    continue
                if in_component_names:
                    in_component_names = False
                i += 1
            if not has_component_scoping:
                return GLOBAL_COVERAGE
        else:
            i += 1

    return components


def _parse_components_from_description(description: str) -> list[str]:
    """Extract component names from a skill-generated MR description.

    Handles two formats produced by ``_build_mr_body`` in ``create_gitlab_mr.py``:

    **Single-version** — flat ``### Components`` section::

        ### Components
        - `odh-dashboard-v3-4`
        - `odh-modelmesh-serving-v3-4`

    **Multi-version** — per-version subsections::

        ### `rhoai-3.4`
        **Components**:
        - `odh-dashboard-v3-4`

    All components are collected into a single flat list regardless of
    which version section they belong to.
    """
    components: list[str] = []
    comp_re = re.compile(r"^-\s+`([^`]+)`")

    in_components = False
    for line in description.splitlines():
        stripped = line.strip()

        if stripped == "### Components" or stripped.startswith("**Components**"):
            in_components = True
            continue

        if stripped.startswith("### ") and stripped != "### Components":
            in_components = False
            if "rhoai-" in stripped:
                continue
            continue

        if in_components:
            m = comp_re.match(stripped)
            if m:
                components.append(m.group(1))
            elif stripped and not stripped.startswith("-"):
                in_components = False

    return components


class _MRCache:
    """In-memory cache for MR diffs fetched via the GitLab API.

    Built once by ``prefetch_open_mrs()`` in batch mode so that
    ``analyze_mr_component_coverage()`` never issues redundant API calls.
    In single-violation mode the cache is empty and diffs are fetched on demand.
    """

    def __init__(self) -> None:
        self._diffs: dict[int, list[dict]] = {}  # iid -> changes list

    def has(self, iid: int) -> bool:
        return iid in self._diffs

    def get_changes(self, iid: int) -> list[dict]:
        return self._diffs.get(iid, [])

    def store(self, iid: int, changes: list[dict]) -> None:
        self._diffs[iid] = changes

    def prefetch(self, iids: list[int]) -> None:
        """Fetch diffs for all *iids* that are not already cached."""
        try:
            project = _get_project()
        except Exception:
            for iid in iids:
                if not self.has(iid):
                    self.store(iid, [])
            return

        for iid in iids:
            if self.has(iid):
                continue
            try:
                mr = project.mergerequests.get(iid)
                changes = mr.changes()
                self.store(iid, changes.get("changes", []))
            except Exception:
                self.store(iid, [])


_mr_cache = _MRCache()


def prefetch_open_mrs(rules: list[str]) -> dict[str, list[dict]]:
    """Search for open Merge Requests across all *rules* and prefetch their diffs.

    Returns a mapping of ``rule -> list[mr_info]`` (same shape as
    ``search_open_exception_mrs`` output).  All unique Merge Request diffs
    are fetched once and stored in ``_mr_cache`` so that downstream calls
    to ``analyze_mr_component_coverage`` hit the cache instead of the API.

    Rule searches run in parallel (each thread gets its own GitLab client
    via ``_get_project()``).  Diff prefetch is sequential after all
    searches complete.
    """
    rule_to_mrs: dict[str, list[dict]] = {}
    all_iids: set[int] = set()

    with ThreadPoolExecutor(max_workers=min(len(rules), 4)) as pool:
        futures = {pool.submit(search_open_exception_mrs, r): r for r in rules}
        for future in as_completed(futures):
            rule = futures[future]
            try:
                mrs = future.result()
            except Exception:
                mrs = []
            rule_to_mrs[rule] = mrs
            for mr in mrs:
                all_iids.add(mr["iid"])

    _mr_cache.prefetch(sorted(all_iids))
    return rule_to_mrs


def _build_coverage_result(
    base: dict,
    mr_components: list[str],
    requested_components: list[str],
    source: str,
    aliases: dict[str, set[str]] | None = None,
) -> dict:
    """Compute overlap between MR components and requested components.

    When *aliases* is provided, expanded sets are intersected and the
    result is mapped back to the original requested names.
    """
    mr_set = set(mr_components)
    req_set = set(requested_components)

    if aliases:
        import component_alias_ops
        mr_expanded = component_alias_ops.expand_component_set(mr_set, aliases)
        req_expanded = component_alias_ops.expand_component_set(req_set, aliases)
        expanded_overlap = mr_expanded & req_expanded
        covered = sorted(expanded_overlap & req_set)
        missing = sorted(req_set - set(covered))
    else:
        covered = sorted(mr_set & req_set)
        missing = sorted(req_set - mr_set)

    if not covered:
        suggestion = "no_overlap"
    elif not missing:
        suggestion = "fully_covered"
    else:
        suggestion = "extend_mr"

    return {
        **base,
        "mr_components": mr_components,
        "covered": covered,
        "missing": missing,
        "source": source,
        "suggestion": suggestion,
    }


def analyze_mr_component_coverage(
    mr_iid: int,
    rule: str,
    requested_components: list[str],
    mr_description: str = "",
    aliases: dict[str, set[str]] | None = None,
) -> dict:
    """Analyze which requested components an open Merge Request already covers.

    Primary: parse the Merge Request diff for added ``componentNames`` under
    the rule.
    Fallback: parse the structured Merge Request description (for Merge
    Requests that only change ``effectiveUntil`` or where the diff yields
    nothing).

    Each result includes ``mr_type`` (``"exception"`` or ``"remedy"``)
    determined by :func:`classify_mr_type` from the diff file paths.

    Uses ``_mr_cache`` if the diff was prefetched; otherwise fetches on demand.
    """
    result_base: dict = {
        "mr_iid": mr_iid,
        "mr_type": "exception",
        "mr_components": [],
        "covered": [],
        "missing": list(requested_components),
        "source": "none",
        "suggestion": "no_overlap",
    }

    # --- Primary: diff parsing (cache-aware) ---
    diff_components: list[str] = []
    changes: list[dict] = []
    if _mr_cache.has(mr_iid):
        changes = _mr_cache.get_changes(mr_iid)
    else:
        try:
            project = _get_project()
            mr = project.mergerequests.get(mr_iid)
            changes_data = mr.changes()
            changes = changes_data.get("changes", [])
            _mr_cache.store(mr_iid, changes)
        except Exception:
            result_base["coverage_error"] = "Failed to fetch Merge Request diff"

    result_base["mr_type"] = classify_mr_type(changes)

    for change in changes:
        path = change.get("new_path", "")
        if any(marker in path for marker in EXCEPTION_PATH_MARKERS):
            diff_components.extend(_parse_components_from_diff(change.get("diff", ""), rule))

    if diff_components:
        if "*" in diff_components:
            return {
                **result_base,
                "mr_components": GLOBAL_COVERAGE,
                "covered": sorted(requested_components),
                "missing": [],
                "source": "diff",
                "suggestion": "fully_covered",
            }
        mr_comps = sorted(set(diff_components))
        return _build_coverage_result(
            result_base,
            mr_comps,
            requested_components,
            source="diff",
            aliases=aliases,
        )

    # --- Fallback: description parsing ---
    if mr_description:
        desc_components = _parse_components_from_description(mr_description)
        if desc_components:
            mr_comps = sorted(set(desc_components))
            return _build_coverage_result(
                result_base,
                mr_comps,
                requested_components,
                source="description",
                aliases=aliases,
            )

    return result_base


def main() -> None:
    parser = argparse.ArgumentParser(description="Conforma Merge Request discovery primitives")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search-open-mrs")
    p_search.add_argument("--rule", required=True)

    p_analyze = sub.add_parser("analyze-coverage")
    p_analyze.add_argument("--mr-iid", type=int, required=True)
    p_analyze.add_argument("--rule", required=True)
    p_analyze.add_argument("--components", required=True)

    args = parser.parse_args()

    if args.command == "search-open-mrs":
        result = search_open_exception_mrs(args.rule)
    elif args.command == "analyze-coverage":
        components = [c.strip() for c in args.components.split(",")]
        result = analyze_mr_component_coverage(
            mr_iid=args.mr_iid,
            rule=args.rule,
            requested_components=components,
        )
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
