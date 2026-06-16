"""conforma_mr_ops.py -- Conforma MR discovery primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse

import gitlab_ops

GITLAB_HOST = os.environ.get("GITLAB_HOST", "")
GITLAB_PROJECT = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")


def _ensure_gitlab_env() -> None:
    """Bridge conforma token discovery to env vars for gitlab_ops."""
    if not os.environ.get("GITLAB_TOKEN"):
        token = gitlab_ops.discover_token()
        if token:
            os.environ["GITLAB_TOKEN"] = token


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


def _glab_get_mrs(search_term: str, timeout: int = 15) -> list[dict]:
    """List open MRs matching a search term via python-gitlab."""
    _ensure_gitlab_env()
    try:
        gl = gitlab_ops.get_client(instance_url=GITLAB_HOST)
        project = gl.projects.get(GITLAB_PROJECT)
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
    """Search for open merge requests in konflux-release-data that mention this rule.

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


def _parse_components_from_diff(diff_text: str, rule: str) -> list[str]:
    """Extract componentNames added for a given rule from a unified diff.

    Scans ``+`` lines for a ``- value: <rule>`` pattern, then collects
    subsequent ``componentNames:`` children.  Handles both policy indent
    (10 spaces) and self-service / zero-indent by stripping leading
    whitespace after removing the ``+`` prefix.
    """
    added_lines: list[str] = []
    for raw in diff_text.splitlines():
        if raw.startswith("+") and not raw.startswith("+++"):
            added_lines.append(raw[1:])  # strip the leading '+'

    components: list[str] = []
    i = 0
    while i < len(added_lines):
        stripped = added_lines[i].strip()
        if stripped == f"- value: {rule}" or stripped == f'- value: "{rule}"':
            i += 1
            in_component_names = False
            while i < len(added_lines):
                s = added_lines[i].strip()
                if not s or s.startswith("- value:"):
                    break
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
        _ensure_gitlab_env()
        try:
            gl = gitlab_ops.get_client(instance_url=GITLAB_HOST)
            project = gl.projects.get(GITLAB_PROJECT)
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
    """Search for open MRs across all *rules* and prefetch their diffs.

    Returns a mapping of ``rule -> list[mr_info]`` (same shape as
    ``search_open_exception_mrs`` output).  All unique MR diffs are
    fetched once and stored in ``_mr_cache`` so that downstream calls
    to ``analyze_mr_component_coverage`` hit the cache instead of the API.
    """
    rule_to_mrs: dict[str, list[dict]] = {}
    all_iids: set[int] = set()

    for rule in rules:
        mrs = search_open_exception_mrs(rule)
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
) -> dict:
    """Compute overlap between MR components and requested components."""
    mr_set = set(mr_components)
    req_set = set(requested_components)
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
) -> dict:
    """Analyze which requested components an open MR already covers.

    Primary: parse the MR diff for added ``componentNames`` under the rule.
    Fallback: parse the structured MR description (for MRs that only change
    ``effectiveUntil`` or where the diff yields nothing).

    Uses ``_mr_cache`` if the diff was prefetched; otherwise fetches on demand.
    """
    result_base: dict = {
        "mr_iid": mr_iid,
        "mr_components": [],
        "covered": [],
        "missing": list(requested_components),
        "source": "none",
        "suggestion": "no_overlap",
    }

    # --- Primary: diff parsing (cache-aware) ---
    diff_components: list[str] = []
    if _mr_cache.has(mr_iid):
        for change in _mr_cache.get_changes(mr_iid):
            path = change.get("new_path", "")
            if "EnterpriseContractPolicy/" in path or "exceptions/" in path:
                diff_components.extend(_parse_components_from_diff(change.get("diff", ""), rule))
    else:
        _ensure_gitlab_env()
        try:
            gl = gitlab_ops.get_client(instance_url=GITLAB_HOST)
            project = gl.projects.get(GITLAB_PROJECT)
            mr = project.mergerequests.get(mr_iid)
            changes_data = mr.changes()
            changes = changes_data.get("changes", [])
            _mr_cache.store(mr_iid, changes)
            for change in changes:
                path = change.get("new_path", "")
                if "EnterpriseContractPolicy/" in path or "exceptions/" in path:
                    diff_components.extend(_parse_components_from_diff(change.get("diff", ""), rule))
        except Exception:
            result_base["coverage_error"] = "Failed to fetch MR diff"

    if diff_components:
        mr_comps = sorted(set(diff_components))
        return _build_coverage_result(
            result_base,
            mr_comps,
            requested_components,
            source="diff",
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
            )

    return result_base


def main() -> None:
    parser = argparse.ArgumentParser(description="Conforma MR discovery primitives")
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
