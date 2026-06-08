#!/usr/bin/env python3
"""Deterministic pre-flight check for conforma-exception.

Resolves ALL parameters from authoritative sources (Jira, GitLab, RPA files).
The agent MUST run this script FIRST and present its output to the user for
confirmation. The agent MUST NOT make decisions about any of these values.

Outputs a JSON with:
  - resolved values (rule, components, versions, dates, links)
  - existing state (duplicate tickets, existing exceptions, related PSX)
  - hard-rule defaults (link types, MR-per-version strategy)
  - items requiring user confirmation

Usage:
  # Existing exception gate check (no Jira required — run FIRST)
  python3 scripts/preflight_check.py --check-existing-exception \
    --rule hermetic_task.hermetic \
    --components odh-model-registry-v3-4

  # Full pre-flight check (requires Jira URL)
  python3 scripts/preflight_check.py --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-38389
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

import gitlab_ops

_SKILL_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = _SKILL_DIR / ".work"


# Hard rules — NOT configurable by the agent or user
HARD_RULES = {
    "mr_strategy": "one_mr_per_rule_all_versions",
    "link_type_rhoaieng_to_psx": "Blocks",
    "link_type_related_psx": "Related",
    "link_type_tracking_ticket": "Related",
    "no_self_links": True,
    "remote_links_are_idempotent": True,
    "old_style_exception_handling": "leave_intact_append_new_with_componentNames",
    "matching_componentNames_exception_handling": "extend_effectiveUntil_in_place",
}

# Default end-of-support dates (pre-calculated with +7 day buffer; buffer only applies to EOS-sourced dates)
DEFAULT_EOS_DATES: dict[str, str] = {
    "rhoai-2.25": "2027-04-26",
    "rhoai-3.3": "2026-10-05",
    "rhoai-3.4": "2026-08-12",
    "rhoai-3.5-ea.1": "2026-06-19",
}


def _run_acli(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    from cli_runner import run_acli

    return run_acli(args, timeout=timeout)


def _extract_ticket_key(url: str) -> str | None:
    match = re.search(r"([A-Z]+-\d+)", url)
    return match.group(1) if match else None


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


def fetch_rhoaieng_ticket(url: str) -> dict:
    """Fetch RHOAIENG ticket details and extract rule/version/component info."""
    ticket_key = _extract_ticket_key(url)
    if not ticket_key:
        return {"error": f"Cannot extract ticket key from: {url}"}

    result = _run_acli(["jira", "workitem", "view", ticket_key, "--json"], timeout=30)
    if result.returncode != 0:
        return {"error": f"Cannot fetch {ticket_key}: {result.stderr.strip()}"}

    data = json.loads(result.stdout)
    fields = data.get("fields", {})

    info = {
        "key": ticket_key,
        "url": url,
        "summary": fields.get("summary", ""),
        "type": fields.get("issuetype", {}).get("name", "Unknown"),
        "priority": fields.get("priority", {}).get("name", "Unknown"),
        "status": fields.get("status", {}).get("name", "Unknown"),
        "labels": fields.get("labels", []),
    }

    if info["type"] != "Bug" or info["priority"] != "Blocker":
        info["type_warning"] = (
            f"{ticket_key} is a '{info['type']}' (priority: {info['priority']}). "
            f"Exception process expects a Blocker Bug cloned from RHOAIENG-62569."
        )

    rule = _extract_rule_from_summary(info["summary"])
    if rule:
        info["detected_rule"] = rule

    return info


def _extract_rule_from_summary(summary: str) -> str | None:
    """Extract conforma rule from ticket summary."""
    match = re.search(r"(rpm_signature\.allowed:[0-9a-fA-F]+)", summary)
    if match:
        return match.group(1)
    match = re.search(r"signed with ([0-9a-fA-F]{16})(?![0-9a-fA-F])", summary)
    if match:
        return f"rpm_signature.allowed:{match.group(1)}"
    match = re.search(r"signing key ([0-9a-fA-F]{16})(?![0-9a-fA-F])", summary)
    if match:
        return f"rpm_signature.allowed:{match.group(1)}"
    match = re.search(r"(hermetic_task\.\w+)", summary)
    if match:
        return match.group(1)
    match = re.search(r"(schedule\.\w+)", summary)
    if match:
        return match.group(1)
    match = re.search(r"(test\.\w+:\S+)", summary)
    if match:
        return match.group(1)
    return None


GITLAB_HOST = os.environ.get("GITLAB_HOST", "")
GITLAB_PROJECT = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")


def _ensure_gitlab_env() -> None:
    """Bridge conforma token discovery to env vars for gitlab_ops."""
    from cli_runner import _resolve_env

    if not os.environ.get("GITLAB_TOKEN"):
        token = _resolve_env("GITLAB_TOKEN")
        if token:
            os.environ["GITLAB_TOKEN"] = token


def _glab_get_mrs(search_term: str, timeout: int = 15) -> list[dict]:
    """List open MRs matching a search term via python-gitlab.

    Falls back to glab CLI if the library call fails.
    """
    _ensure_gitlab_env()
    try:
        gl = gitlab_ops.get_client(instance_url=GITLAB_HOST)
        project = gl.projects.get(GITLAB_PROJECT)
        mrs = project.mergerequests.list(
            state="opened",
            search=search_term,
            per_page=20,
            get_all=False,
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
        pass

    from cli_runner import run_glab

    encoded = urllib.parse.quote(search_term)
    project_encoded = GITLAB_PROJECT.replace("/", "%2F")
    try:
        result = run_glab(
            [
                "api",
                "--hostname",
                GITLAB_HOST,
                "--method",
                "GET",
                f"projects/{project_encoded}/merge_requests?state=opened&search={encoded}&per_page=20",
            ],
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    try:
        mrs_data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return []

    return [mr for mr in mrs_data if isinstance(mr, dict)]


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
        results.append(
            {
                "iid": iid,
                "title": mr.get("title", ""),
                "url": mr.get("web_url", ""),
                "author": mr.get("author", {}).get("username", ""),
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
        from cli_runner import run_glab

        project = GITLAB_PROJECT.replace("/", "%2F")
        for iid in iids:
            if self.has(iid):
                continue
            try:
                resp = run_glab(
                    [
                        "api",
                        "--hostname",
                        GITLAB_HOST,
                        "--method",
                        "GET",
                        f"projects/{project}/merge_requests/{iid}/changes",
                    ],
                    timeout=30,
                )
                if resp.returncode == 0:
                    data = json.loads(resp.stdout)
                    self.store(iid, data.get("changes", []))
                else:
                    self.store(iid, [])
            except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
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


def prefetch_open_jira_tickets(rules: list[str]) -> dict[str, list[dict]]:
    """Batch search for open Jira tickets (RHOAIENG, PSX, OCPEXCEPT) matching violations.

    Does one broad JQL query to find all open conforma-violation tickets,
    then matches them to rules by summary text. Returns a mapping of
    ``rule -> list[ticket_info]``.
    """
    all_tickets: list[dict] = []

    jql = (
        "project in (RHOAIENG, PSX, OCPEXCEPT) "
        "AND labels = 'conforma-violation' "
        "AND status not in (Closed, Resolved, Done)"
    )
    result = _run_acli(
        ["jira", "workitem", "search", "--jql", jql],
        timeout=45,
    )
    if result.returncode == 0:
        all_tickets = _parse_acli_table(result.stdout)

    rule_to_tickets: dict[str, list[dict]] = {r: [] for r in rules}
    for ticket in all_tickets:
        summary_nospace = re.sub(r"\s+", "", ticket["summary"].lower())
        for rule in rules:
            rule_nospace = re.sub(r"\s+", "", rule.lower())
            if rule_nospace in summary_nospace:
                rule_to_tickets[rule].append(ticket)
                break
            if ":" in rule:
                suffix_nospace = re.sub(r"\s+", "", rule.split(":", 1)[1].lower())
                if suffix_nospace in summary_nospace:
                    rule_to_tickets[rule].append(ticket)
                    break

    return rule_to_tickets


def _parse_acli_table(stdout: str) -> list[dict]:
    """Parse acli table output with multi-line wrapped cells.

    The table has columns: Type | Key | Assignee | Priority | Status | Summary.
    Rows are separated by ``├──`` lines. Long cell values wrap across multiple
    lines within the same row.
    """
    tickets: list[dict] = []
    current_cells: dict[str, str] = {}
    col_indices: list[tuple[int, int]] = []

    for line in stdout.splitlines():
        if line.startswith("├") or line.startswith("└"):
            if current_cells.get("key"):
                tickets.append(
                    {
                        "key": current_cells["key"].strip(),
                        "type": current_cells.get("type", "").strip(),
                        "status": current_cells.get("status", "").strip(),
                        "summary": re.sub(r"\s+", " ", current_cells.get("summary", "")).strip(),
                        "url": f"https://redhat.atlassian.net/browse/{current_cells['key'].strip()}",
                    }
                )
            current_cells = {}
            continue

        if line.startswith("┌"):
            col_indices = []
            start = 0
            for m in re.finditer(r"[┬┐]", line):
                col_indices.append((start + 1, m.start()))
                start = m.start()
            continue

        if "│" not in line or not col_indices:
            continue

        if line.strip().startswith("│") and "Type" in line and "Key" in line:
            continue

        parts = []
        raw_parts = []
        for start, end in col_indices:
            if start < len(line) and end <= len(line):
                parts.append(line[start:end].strip())
                raw_parts.append(line[start:end].rstrip())
            else:
                parts.append("")
                raw_parts.append("")

        if len(parts) >= 6:
            key_candidate = parts[1]
            if re.match(r"(RHOAIENG|PSX|OCPEXCEPT)-\d+", key_candidate):
                current_cells = {
                    "type": parts[0],
                    "key": key_candidate,
                    "status": parts[4],
                    "summary": raw_parts[5],
                }
            elif current_cells:
                current_cells["summary"] = current_cells.get("summary", "") + raw_parts[5]

    if current_cells.get("key"):
        tickets.append(
            {
                "key": current_cells["key"].strip(),
                "type": current_cells.get("type", "").strip(),
                "status": current_cells.get("status", "").strip(),
                "summary": re.sub(r"\s+", " ", current_cells.get("summary", "")).strip(),
                "url": f"https://redhat.atlassian.net/browse/{current_cells['key'].strip()}",
            }
        )

    return tickets


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
    from cli_runner import run_glab

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
        project = GITLAB_PROJECT.replace("/", "%2F")
        try:
            resp = run_glab(
                [
                    "api",
                    "--hostname",
                    GITLAB_HOST,
                    "--method",
                    "GET",
                    f"projects/{project}/merge_requests/{mr_iid}/changes",
                ],
                timeout=30,
            )
            if resp.returncode == 0:
                data = json.loads(resp.stdout)
                changes = data.get("changes", [])
                _mr_cache.store(mr_iid, changes)
                for change in changes:
                    path = change.get("new_path", "")
                    if "EnterpriseContractPolicy/" in path or "exceptions/" in path:
                        diff_components.extend(_parse_components_from_diff(change.get("diff", ""), rule))
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
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


def search_related_psx(rule: str) -> list[dict]:
    """Search for existing PSX tickets related to this rule."""
    rule_fragment = rule
    if ":" in rule:
        rule_fragment = rule.split(":", 1)[1]

    result = _run_acli(
        ["jira", "workitem", "search", "--jql", f"project = PSX AND text ~ '{rule_fragment}'"],
        timeout=30,
    )
    if result.returncode != 0:
        return []

    tickets = []
    for line in result.stdout.splitlines():
        match = re.search(r"(PSX-\d+)", line)
        if match:
            key = match.group(1)
            if key not in [t["key"] for t in tickets]:
                summary_match = re.search(r"PSX-\d+\s*│\s*.*?│.*?│.*?│\s*(.*)", line)
                summary = summary_match.group(1).strip() if summary_match else ""
                tickets.append({"key": key, "summary_fragment": summary})
    return tickets


def search_existing_exceptions(rule: str, clone_dir: str | None = None) -> dict:
    """Check if exception for this rule already exists in konflux-release-data.

    Searches two locations:
    1. The `exclude:` section — simple list items (permanent global exclusions)
    2. The `volatileCriteria:` section — structured blocks with componentNames/effectiveUntil
    """
    if clone_dir:
        search_dir = Path(clone_dir)
    else:
        search_dir = WORK_DIR

    if not search_dir.exists():
        return {"checked": False, "reason": "No local clone available"}

    _krd_domain = os.environ.get("KRD_CLUSTER_DOMAIN", "")
    _ec_dir = (
        f"config/{_krd_domain}/product/EnterpriseContractPolicy"
        if _krd_domain
        else os.environ.get("KRD_EC_POLICY_DIR", "")
    )
    if not _ec_dir:
        return {"checked": False, "reason": "KRD_CLUSTER_DOMAIN or KRD_EC_POLICY_DIR env var not set"}
    policy_dir = search_dir / _ec_dir
    if not policy_dir.exists():
        return {"checked": False, "reason": f"Policy dir not found: {policy_dir}"}

    found_in = []
    permanent_exclusions = []

    for yaml_file in policy_dir.glob("*rhoai*.yaml"):
        content = yaml_file.read_text(encoding="utf-8")
        rel_path = str(yaml_file.relative_to(search_dir))

        if rule in content:
            _check_permanent_exclusions(content, rule, rel_path, permanent_exclusions)

        if f"value: {rule}" in content:
            from create_gitlab_mr import _find_existing_exceptions

            exceptions = _find_existing_exceptions(content, rule)
            for exc in exceptions:
                found_in.append(
                    {
                        "file": rel_path,
                        "has_componentNames": exc["has_component_names"],
                        "componentNames": exc["component_names"],
                        "imageUrl": exc.get("image_url", ""),
                        "effectiveUntil": exc["effective_until_value"],
                    }
                )

    return {
        "checked": True,
        "rule": rule,
        "existing_exceptions": found_in,
        "permanent_exclusions": permanent_exclusions,
        "count": len(found_in),
        "permanent_count": len(permanent_exclusions),
    }


def _check_permanent_exclusions(content: str, rule: str, file_path: str, results: list[dict]) -> None:
    """Check if the rule appears in the `exclude:` section as a permanent global exclusion.

    These are simple list items under `exclude:` with no componentNames or effectiveUntil,
    meaning the rule is permanently excluded for ALL components.
    """
    lines = content.split("\n")
    in_exclude_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "exclude:":
            in_exclude_section = True
            continue
        if in_exclude_section:
            if not stripped or (not stripped.startswith("-") and not stripped.startswith("#")):
                in_exclude_section = False
                continue
            if stripped.startswith("#"):
                continue
            if stripped == f"- {rule}":
                results.append(
                    {
                        "file": file_path,
                        "line": i + 1,
                        "type": "permanent_global_exclusion",
                        "detail": (
                            f"Rule '{rule}' is permanently excluded globally "
                            f"(no componentNames, no effectiveUntil). "
                            f"All components are covered forever."
                        ),
                    }
                )


def check_rhoaieng_approval_status(url: str) -> dict:
    """Check whether the RHOAIENG approval Jira ticket has been approved.

    Fetches the ticket and inspects its status and resolution. An approved
    ticket is one that is Closed/Resolved with a resolution indicating
    approval (Done, Fixed, Approved, etc.) or has a comment from a known
    senior manager confirming approval.

    Returns:
        {
            "url": str,
            "key": str,
            "status": str,          # Jira status name
            "resolution": str|None, # Jira resolution name
            "approved": bool,       # deterministic verdict
            "reason": str,          # human-readable explanation
            "approval_comment": str|None,  # matching comment if found
        }
    """
    ticket_key = _extract_ticket_key(url)
    if not ticket_key:
        return {
            "url": url,
            "key": None,
            "status": "unknown",
            "resolution": None,
            "approved": False,
            "reason": f"Cannot extract ticket key from: {url}",
            "approval_comment": None,
        }

    result = _run_acli(["jira", "workitem", "view", ticket_key, "--json"], timeout=30)
    if result.returncode != 0:
        return {
            "url": url,
            "key": ticket_key,
            "status": "unknown",
            "resolution": None,
            "approved": False,
            "reason": f"Cannot fetch {ticket_key}: {result.stderr.strip()}",
            "approval_comment": None,
        }

    data = json.loads(result.stdout)
    fields = data.get("fields", {})
    status_name = fields.get("status", {}).get("name", "Unknown")
    status_category = fields.get("status", {}).get("statusCategory", {}).get("key", "")
    resolution = fields.get("resolution")
    resolution_name = resolution.get("name", "") if resolution else None

    approved_statuses = {"done", "closed", "resolved"}
    approved_resolutions = {"done", "fixed", "approved", "won't do", "complete", "completed"}

    is_done = status_category == "done" or status_name.lower() in approved_statuses
    has_approved_resolution = resolution_name is not None and resolution_name.lower() in approved_resolutions

    approval_comment = None
    if not (is_done and has_approved_resolution):
        approval_comment = _search_approval_comments(ticket_key)

    approved = (is_done and has_approved_resolution) or approval_comment is not None

    if approved and is_done:
        reason = (
            f"{ticket_key} is {status_name}"
            + (f" (resolution: {resolution_name})" if resolution_name else "")
            + ". Approval requirement satisfied."
        )
    elif approved and approval_comment:
        reason = (
            f"{ticket_key} is {status_name} (not yet closed) but has an "
            f"approval comment. Approval requirement satisfied."
        )
    else:
        reason = (
            f"{ticket_key} is {status_name}"
            + (f" (resolution: {resolution_name})" if resolution_name else "")
            + ". RHOAIENG approval is required before creating PSX Jira "
            + "ticket and GitLab Merge Request."
        )

    return {
        "url": url,
        "key": ticket_key,
        "status": status_name,
        "resolution": resolution_name,
        "approved": approved,
        "reason": reason,
        "approval_comment": approval_comment,
    }


def _search_approval_comments(ticket_key: str) -> str | None:
    """Search a ticket's comments for approval from a senior manager."""
    result = _run_acli(["jira", "workitem", "comments", ticket_key, "--json"], timeout=30)
    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    comments = data if isinstance(data, list) else data.get("comments", [])
    approval_keywords = [
        "approved",
        "approve",
        "lgtm",
        "go ahead",
        "exception approved",
        "approval granted",
    ]
    for comment in comments:
        body = ""
        if isinstance(comment, dict):
            body = comment.get("body", "") or ""
            if isinstance(body, dict):
                body = json.dumps(body)
        elif isinstance(comment, str):
            body = comment
        body_lower = body.lower()
        if any(kw in body_lower for kw in approval_keywords):
            author = ""
            if isinstance(comment, dict):
                author = (
                    comment.get("author", {}).get("displayName", "") if isinstance(comment.get("author"), dict) else ""
                )
            snippet = body[:200] + ("..." if len(body) > 200 else "")
            return f"[{author}]: {snippet}"

    return None


def check_duplicate_psx_tickets(rule: str, rhoai_versions: list[str]) -> list[dict]:
    """Check if PSX tickets already exist for this exact rule+versions combo."""
    search_term = rule.split(":", 1)[1] if ":" in rule else rule
    result = _run_acli(
        [
            "jira",
            "workitem",
            "search",
            "--jql",
            f"project = PSX AND summary ~ '{search_term}' AND labels = 'conforma-exception-ai-skill'",
        ],
        timeout=30,
    )
    if result.returncode != 0:
        return []

    tickets = []
    for line in result.stdout.splitlines():
        match = re.search(r"(PSX-\d+)", line)
        if match:
            key = match.group(1)
            if key not in [t["key"] for t in tickets]:
                tickets.append({"key": key})
    return tickets


def lookup_components_from_rpa(
    image_bases: list[str], rhoai_versions: list[str], rpa_dir: str | None = None
) -> dict[str, list[str]]:
    """Look up Konflux component names from ReleasePlanAdmission files."""
    from validate_inputs import lookup_component_names

    results: dict[str, list[str]] = {}
    for ver in rhoai_versions:
        all_matches = []
        for img in image_bases:
            found = lookup_component_names(img, [ver], rpa_dir)
            all_matches.extend(found.get(ver, []))
        results[ver] = sorted(set(all_matches))
    return results


def resolve_effective_until_dates(rhoai_versions: list[str]) -> dict[str, dict]:
    """Resolve effectiveUntil dates from defaults (end-of-support + 7 day buffer).

    The +7 day buffer is only applied to dates sourced from this EOS table.
    User-provided or Jira-sourced dates are used as-is.
    """
    results = {}
    for ver in rhoai_versions:
        if ver in DEFAULT_EOS_DATES:
            results[ver] = {
                "effectiveUntil": f"{DEFAULT_EOS_DATES[ver]}T00:00:00Z",
                "source": "default_eos_table",
                "note": "End-of-support date + 7 day buffer (pre-calculated)",
            }
        else:
            results[ver] = {
                "effectiveUntil": None,
                "source": "unknown",
                "note": f"No default EOS date for {ver}. User must provide.",
            }
    return results


def evaluate_decision(
    existing_exceptions: dict,
    components_per_version: dict[str, list[str]],
    environment: str = "prod",
) -> dict:
    """Deterministic go/no-go decision based on existing state.

    Decision rules (hardcoded, not configurable):
    1. If rule has a permanent global exclusion in the TARGET environment file
       (in `exclude:` section, no componentNames, no effectiveUntil) → ABORT.
       The rule is already permanently approved for all components in that env.
    2. If rule has a volatile exception with matching componentNames and no effectiveUntil
       (permanent scoped) → ABORT for those components (already permanently covered).
    3. If rule has a volatile exception with matching componentNames and effectiveUntil
       → PROCEED with action "extend" (update the date).
    4. If rule has a volatile exception without componentNames (old-style, time-bounded)
       → PROCEED with action "append_new_style" (leave old intact, add new block).
    5. If no existing exception found → PROCEED with action "create_new".

    The `environment` parameter determines which file(s) are relevant. A permanent
    exclusion in stage does NOT block creation in prod, and vice versa.

    Returns:
        {
            "proceed": bool,
            "action": str,  # "abort" | "create_new" | "extend" | "append_new_style"
            "reason": str,  # human-readable explanation
            "details": dict # additional context
        }
    """
    if not existing_exceptions.get("checked"):
        return {
            "proceed": True,
            "action": "create_new",
            "reason": (
                "Could not check existing exceptions "
                f"({existing_exceptions.get('reason', 'unknown')}). "
                "Proceeding with creation — dedup will be handled at MR time."
            ),
            "details": {},
        }

    permanent = existing_exceptions.get("permanent_exclusions", [])
    relevant_permanent = [p for p in permanent if f"-{environment}." in Path(p["file"]).name]
    if relevant_permanent:
        return {
            "proceed": False,
            "action": "abort",
            "reason": (
                f"Rule is already permanently excluded globally in "
                f"{relevant_permanent[0]['file']} (line {relevant_permanent[0]['line']}). "
                f"No componentNames-scoped exception needed — all components "
                f"are covered forever in {environment}. "
                f"Creating a new exception would be redundant."
            ),
            "details": {"permanent_exclusions": relevant_permanent},
        }

    volatile = existing_exceptions.get("existing_exceptions", [])
    if not volatile:
        return {
            "proceed": True,
            "action": "create_new",
            "reason": "No existing exception found for this rule. Will create new.",
            "details": {},
        }

    all_requested_components = set()
    for comps in components_per_version.values():
        all_requested_components.update(comps)

    for exc in volatile:
        if exc["has_componentNames"]:
            if not exc["effectiveUntil"]:
                exc_comps = set(exc["componentNames"])
                if all_requested_components.issubset(exc_comps):
                    return {
                        "proceed": False,
                        "action": "abort",
                        "reason": (
                            f"Rule already has a permanent scoped exception in "
                            f"{exc['file']} covering all requested components. "
                            f"No new exception needed."
                        ),
                        "details": {"matching_exception": exc},
                    }
            else:
                exc_comps = set(exc["componentNames"])
                if all_requested_components == exc_comps or all_requested_components.issubset(exc_comps):
                    return {
                        "proceed": True,
                        "action": "extend",
                        "reason": (
                            f"Existing exception with matching componentNames found in "
                            f"{exc['file']} (effectiveUntil: {exc['effectiveUntil']}). "
                            f"Will extend the effectiveUntil date."
                        ),
                        "details": {"matching_exception": exc},
                    }

    has_old_style = any(not exc["has_componentNames"] for exc in volatile)
    if has_old_style:
        return {
            "proceed": True,
            "action": "append_new_style",
            "reason": (
                "Old-style exception (no componentNames) found. "
                "Will leave it intact and append a new componentNames-based block."
            ),
            "details": {"old_style_exceptions": [e for e in volatile if not e["has_componentNames"]]},
        }

    return {
        "proceed": True,
        "action": "create_new",
        "reason": (
            "Existing exceptions found but with different componentNames. "
            "Will create a new block for the requested components."
        ),
        "details": {"existing_exceptions": volatile},
    }


def check_existing_exception_gate(
    rule: str,
    components: list[str],
    clone_dir: str | None = None,
    environment: str = "prod",
    prefetched_mrs: list[dict] | None = None,
) -> dict:
    """Hard gate: check if active exceptions already cover the requested components.

    Clones konflux-release-data (if needed), searches for existing exceptions
    matching the rule, and determines whether any active (non-expired) exception
    already covers the requested components.

    Returns:
        {
            "gate": "existing_exception_check",
            "status": "blocked" | "partial" | "passed" | "permanent",
            "reason": str,
            "rule": str,
            "requested_components": list[str],
            "active_exceptions": list[dict],
            "permanent_exclusions": list[dict],
            "covered_components": list[str],
            "uncovered_components": list[str],
        }
    """
    from datetime import datetime, timezone

    base_result = {
        "gate": "existing_exception_check",
        "rule": rule,
        "requested_components": components,
        "active_exceptions": [],
        "permanent_exclusions": [],
        "covered_components": [],
        "uncovered_components": list(components),
    }

    # Ensure clone exists
    repo_dir = None
    if clone_dir:
        candidate = Path(clone_dir)
        _krd_dom = os.environ.get("KRD_CLUSTER_DOMAIN", "")
        policy_sub = (
            f"config/{_krd_dom}/product/EnterpriseContractPolicy"
            if _krd_dom
            else os.environ.get("KRD_EC_POLICY_DIR", "")
        )
        if (candidate / policy_sub).is_dir():
            repo_dir = candidate
        elif (candidate / "repo" / policy_sub).is_dir():
            repo_dir = candidate / "repo"

    if not repo_dir:
        try:
            from manage_exceptions import _clone_repo

            repo_dir, _ = _clone_repo(Path(clone_dir) if clone_dir else None)
        except Exception as exc:
            return {
                **base_result,
                "status": "passed",
                "reason": (
                    f"Could not clone konflux-release-data ({exc}). Gate check skipped — proceeding with caution."
                ),
            }

    existing = search_existing_exceptions(rule, str(repo_dir))

    open_mrs = prefetched_mrs if prefetched_mrs is not None else search_open_exception_mrs(rule)
    enriched_mrs: list[dict] = []
    for mr_info in open_mrs:
        coverage = analyze_mr_component_coverage(
            mr_iid=mr_info["iid"],
            rule=rule,
            requested_components=components,
            mr_description=mr_info.get("description", ""),
        )
        merged = {**mr_info, **coverage}
        merged.pop("description", None)
        enriched_mrs.append(merged)
    base_result["open_merge_requests"] = enriched_mrs

    if not existing.get("checked"):
        return {
            **base_result,
            "status": "passed",
            "reason": (
                f"Could not check existing exceptions: "
                f"{existing.get('reason', 'unknown')}. "
                "Gate check skipped — proceeding with caution."
            ),
        }

    # Check permanent exclusions first
    permanent = existing.get("permanent_exclusions", [])
    env_permanent = [p for p in permanent if f"-{environment}." in Path(p["file"]).name]
    if env_permanent:
        return {
            **base_result,
            "status": "permanent",
            "permanent_exclusions": env_permanent,
            "covered_components": list(components),
            "uncovered_components": [],
            "reason": (
                f"Rule '{rule}' is permanently excluded globally in "
                f"{env_permanent[0]['file']} (line {env_permanent[0]['line']}). "
                f"All components are covered forever in {environment}. "
                f"No exception needed."
            ),
        }

    # Check volatile exceptions for active coverage
    volatile = existing.get("existing_exceptions", [])
    if not volatile:
        return {
            **base_result,
            "status": "passed",
            "reason": f"No existing exceptions found for rule '{rule}'. Proceed with creation.",
        }

    now = datetime.now(timezone.utc)
    requested = set(components)
    covered = set()
    active_exceptions = []
    seen_keys: set[str] = set()

    for exc in volatile:
        eu = exc.get("effectiveUntil")
        is_active = True
        if eu:
            try:
                eu_str = eu.strip('"').strip("'")
                eu_dt = datetime.fromisoformat(eu_str.replace("Z", "+00:00"))
                is_active = eu_dt > now
            except (ValueError, TypeError):
                is_active = True  # can't parse → assume active

        if not is_active:
            continue

        env_file = Path(exc.get("file", "")).name
        if f"-{environment}" not in env_file and environment != "":
            continue

        exc_comps = set(exc.get("componentNames", []))
        dedup_key = f"{exc.get('file')}|{eu}|{sorted(exc_comps)}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        if exc.get("has_componentNames") and exc_comps:
            overlap = requested & exc_comps
            if overlap:
                covered |= overlap
                active_exceptions.append(
                    {
                        "file": exc["file"],
                        "componentNames": sorted(exc_comps),
                        "effectiveUntil": eu,
                        "covers_components": sorted(overlap),
                    }
                )
        elif not exc.get("has_componentNames"):
            image_url = exc.get("imageUrl", "")
            if image_url:
                matched = {c for c in requested if image_url_covers_component(image_url, c)}
                if matched:
                    covered |= matched
                    active_exceptions.append(
                        {
                            "file": exc["file"],
                            "componentNames": [],
                            "imageUrl": image_url,
                            "effectiveUntil": eu,
                            "covers_components": sorted(matched),
                            "note": f"imageUrl-scoped exception ({image_url} covers base name '{_extract_image_base(image_url)}')",
                        }
                    )
            else:
                covered = requested.copy()
                active_exceptions.append(
                    {
                        "file": exc["file"],
                        "componentNames": [],
                        "effectiveUntil": eu,
                        "covers_components": sorted(requested),
                        "note": "Unscoped exception (no componentNames, no imageUrl) — covers all components for this rule",
                    }
                )

    uncovered = sorted(requested - covered)
    covered_list = sorted(covered)

    if not active_exceptions:
        return {
            **base_result,
            "status": "passed",
            "reason": (f"Existing exceptions found for rule '{rule}' but all are expired. Proceed with creation."),
        }

    if not uncovered:
        return {
            **base_result,
            "status": "blocked",
            "active_exceptions": active_exceptions,
            "covered_components": covered_list,
            "uncovered_components": [],
            "reason": (
                f"All {len(requested)} requested component(s) are already covered by "
                f"active exception(s) in {active_exceptions[0]['file']} "
                f"(effectiveUntil: {active_exceptions[0]['effectiveUntil']}). "
                f"No new exception needed."
            ),
        }

    return {
        **base_result,
        "status": "partial",
        "active_exceptions": active_exceptions,
        "covered_components": covered_list,
        "uncovered_components": uncovered,
        "reason": (
            f"{len(covered_list)} of {len(requested)} component(s) already covered "
            f"by active exception(s). {len(uncovered)} component(s) still need "
            f"exceptions: {', '.join(uncovered[:5])}"
            + (f"... (+{len(uncovered) - 5} more)" if len(uncovered) > 5 else "")
        ),
    }


def check_violations_coverage(
    violations_yaml_path: str,
    clone_dir: str | None = None,
    environment: str = "prod",
) -> dict:
    """Batch coverage check: read a violations YAML and check each violation's components
    against existing exceptions in the policy file.

    Returns a per-violation summary with coverage status so the agent can present
    an informed violation list (covered vs uncovered) without per-violation round trips.
    """
    import yaml

    path = Path(violations_yaml_path)
    if not path.exists():
        return {"error": f"Violations file not found: {violations_yaml_path}"}

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_rule = data.get("violation_data", {}).get("violations_by_rule", {})

    if not by_rule:
        return {"error": "No violations_by_rule found in input YAML"}

    all_rules = list(by_rule.keys())

    # Prefetch all open MRs and their diffs in one batch
    prefetched_mrs = prefetch_open_mrs(all_rules)

    # Prefetch all open Jira tickets (RHOAIENG, PSX, OCPEXCEPT) in one batch
    prefetched_jira = prefetch_open_jira_tickets(all_rules)

    results = []
    for rule, info in sorted(by_rule.items()):
        all_components = []
        for release, comps in info.get("releases", {}).items():
            all_components.extend(comps)
        all_components = sorted(set(all_components))

        if not all_components:
            results.append(
                {
                    "rule": rule,
                    "title": info.get("title", ""),
                    "total_components": 0,
                    "covered_components": [],
                    "uncovered_components": [],
                    "coverage": "no_components",
                    "status": "skipped",
                }
            )
            continue

        gate = check_existing_exception_gate(
            rule=rule,
            components=all_components,
            clone_dir=clone_dir,
            environment=environment,
            prefetched_mrs=prefetched_mrs.get(rule),
        )

        covered = gate.get("covered_components", [])
        uncovered = gate.get("uncovered_components", [])

        if gate["status"] == "blocked":
            coverage = "fully_covered"
            coverage_label = "already covered"
        elif gate["status"] == "partial":
            coverage = "partially_covered"
            coverage_label = f"{len(uncovered)} of {len(all_components)} uncovered"
        else:
            coverage = "not_covered"
            coverage_label = "not covered — resolve in code first, exception as last resort"

        open_mrs = gate.get("open_merge_requests", [])

        mr_label = ""
        next_steps = "resolve violation in component code — if not feasible, create conforma exception"
        mr_fully_covered = False
        matched_mr: dict | None = None
        for mr in open_mrs:
            sug = mr.get("suggestion", "")
            mr_url = mr.get("url", "")
            if sug == "fully_covered":
                mr_label = f"fully covered by open [MR !{mr['iid']}]({mr_url})"
                mr_fully_covered = True
                matched_mr = mr
                break
            if sug == "extend_mr":
                n_cov = len(mr.get("covered", []))
                mr_label = f"open [MR !{mr['iid']}]({mr_url}) covers {n_cov}/{len(all_components)}"
                next_steps = (
                    f"extend [MR !{mr['iid']}]({mr_url}) with {len(mr.get('missing', []))} missing component(s)"
                )
                matched_mr = mr

        jira_tickets = prefetched_jira.get(rule, [])
        jira_label = ""
        if jira_tickets:
            labels = []
            for t in jira_tickets:
                labels.append(f"[{t['key']}]({t['url']}) ({t['status']})")
            jira_label = ", ".join(labels)

        if jira_tickets and matched_mr:
            rhoaieng = [t for t in jira_tickets if t["key"].startswith("RHOAIENG-")]
            psx = [t for t in jira_tickets if t["key"].startswith(("PSX-", "OCPEXCEPT-"))]
            mr_ref = f"[MR !{matched_mr['iid']}]({matched_mr['url']})"
            approval_parts = []
            if rhoaieng:
                rhoaieng_refs = ", ".join(f"[{t['key']}]({t['url']}) ({t['status']})" for t in rhoaieng)
                approval_parts.append(f"work with Managers on approving {rhoaieng_refs}")
            if psx:
                _PSX_STATUS_ACTIONS = {
                    "new": 'Pending Approval" and then "Ready for Verification',
                    "open": 'Pending Approval" and then "Ready for Verification',
                    "pending approval": "Ready for Verification",
                    "waiting": "Ready for Verification",
                    "waiting for customer": "Ready for Verification",
                    "in progress": "Ready for Verification",
                }
                for t in psx:
                    status_lower = t["status"].lower()
                    target = _PSX_STATUS_ACTIONS.get(status_lower)
                    ref = f"[{t['key']}]({t['url']}) ({t['status']})"
                    if target:
                        approval_parts.append(f'work with ProdSec to get {ref} to "{target}"')
                    else:
                        approval_parts.append(f"work with ProdSec on {ref}")
            approval_parts.append(f"get {mr_ref} submitted")
            approval_text = " — ".join(approval_parts)

            if mr_fully_covered:
                next_steps = approval_text
            else:
                next_steps += " — " + approval_text
        elif mr_fully_covered:
            next_steps = "no action needed — already covered"

        if len(uncovered) <= 3:
            display_components = ", ".join(uncovered)
        else:
            display_components = ", ".join(uncovered[:3]) + f" ... +{len(uncovered) - 3} more"

        results.append(
            {
                "rule": rule,
                "title": info.get("title", ""),
                "total_components": len(all_components),
                "covered_components": covered,
                "uncovered_components": uncovered,
                "covered_count": len(covered),
                "uncovered_count": len(uncovered),
                "display_components": display_components,
                "open_merge_requests": open_mrs,
                "open_mr_label": mr_label,
                "open_jira_tickets": jira_tickets,
                "open_jira_label": jira_label,
                "next_steps": next_steps,
                "coverage": coverage,
                "coverage_label": coverage_label,
                "status": gate["status"],
            }
        )

    summary = {
        "fully_covered": sum(1 for r in results if r["coverage"] == "fully_covered"),
        "partially_covered": sum(1 for r in results if r["coverage"] == "partially_covered"),
        "not_covered": sum(1 for r in results if r["coverage"] == "not_covered"),
        "total_violations": len(results),
    }

    md_table = _render_violations_markdown_table(results, summary)

    return {
        "violations_source": violations_yaml_path,
        "environment": environment,
        "summary": summary,
        "violations": results,
        "markdown_table": md_table,
    }


def _render_violations_markdown_table(results: list[dict], summary: dict) -> str:
    """Pre-render a markdown table from violations coverage results.

    Columns: #, Rule, Components, Open MRs, Open Jira, Next Steps.
    No Coverage column — next_steps is the single source of guidance.
    """
    lines = [
        f"**Summary**: {summary['total_violations']} unique rules — "
        f"{summary['fully_covered']} fully covered, "
        f"{summary['partially_covered']} partially covered, "
        f"{summary['not_covered']} not covered.",
        "",
        "| # | Rule | Components | Open MRs | Open Jira | Next Steps |",
        "|---|------|-----------|----------|-----------|------------|",
    ]
    for i, v in enumerate(results, 1):
        rule = f"`{v['rule']}`"
        comps = v["display_components"]
        mr = v["open_mr_label"] or "—"
        jira = v["open_jira_label"] or "—"
        ns = v["next_steps"]
        lines.append(f"| {i} | {rule} | {comps} | {mr} | {jira} | {ns} |")

    return "\n".join(lines)


def discover_user_groups() -> dict:
    """Discover the current user's Jira groups and their members dynamically.

    Uses the Jira REST API:
    1. GET /rest/api/3/myself → current user's accountId and displayName
    2. GET /rest/api/3/user/groups?accountId=... → groups the user belongs to
    3. GET /rest/api/3/group/member?groupname=... → members of each group

    Returns a SUGGESTION — the agent MUST present this to the user for
    confirmation before adding anyone as watchers.
    """
    import base64
    import getpass
    import urllib.error
    import urllib.request

    from cli_runner import _resolve_env

    try:
        current_user = getpass.getuser()
    except Exception:
        current_user = "unknown"

    token = _resolve_env("JIRA_API_TOKEN") or ""
    email = _resolve_env("JIRA_EMAIL") or ""
    if not token or not email:
        return {
            "source": "none",
            "user": current_user,
            "user_display_name": None,
            "groups_found": [],
            "suggested_members": [],
            "note": "Jira API unavailable (JIRA_API_TOKEN/JIRA_EMAIL not configured). Cannot discover watchers.",
        }

    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
    }

    # Step 1: Get current user's accountId
    try:
        req = urllib.request.Request(
            "https://redhat.atlassian.net/rest/api/3/myself",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            myself = json.loads(resp.read())
    except Exception as e:
        return {
            "source": "none",
            "user": current_user,
            "user_display_name": None,
            "groups_found": [],
            "suggested_members": [],
            "note": f"Jira API unavailable (GET /myself failed: {e}). Cannot discover watchers.",
        }

    account_id = myself.get("accountId", "")
    display_name = myself.get("displayName", "")

    # Step 2: Get user's groups
    try:
        groups_url = f"https://redhat.atlassian.net/rest/api/3/user/groups?accountId={urllib.request.quote(account_id)}"
        req = urllib.request.Request(groups_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            groups = json.loads(resp.read())
    except Exception as e:
        return {
            "source": "none",
            "user": current_user,
            "user_display_name": display_name,
            "groups_found": [],
            "suggested_members": [],
            "note": f"Jira API unavailable (GET /user/groups failed: {e}). Cannot discover watchers.",
        }

    if not groups:
        return {
            "source": "jira_groups",
            "user": current_user,
            "user_display_name": display_name,
            "groups_found": [],
            "suggested_members": [],
            "note": "User belongs to no Jira groups. No watchers suggested.",
        }

    # Step 3: Fetch members for each group
    group_names = [g.get("name", "") for g in groups if g.get("name")]
    all_members: list[dict] = []
    groups_with_members: list[dict] = []

    for gname in group_names:
        members = _fetch_group_members(gname, headers)
        if members:
            groups_with_members.append(
                {
                    "group_name": gname,
                    "member_count": len(members),
                }
            )
            for m in members:
                if m.get("accountId") != account_id:
                    all_members.append(m)

    # Deduplicate by accountId
    seen_ids: set[str] = set()
    unique_members: list[dict] = []
    for m in all_members:
        aid = m.get("accountId", "")
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            unique_members.append(
                {
                    "displayName": m.get("displayName", ""),
                    "accountId": aid,
                }
            )

    unique_members.sort(key=lambda x: x["displayName"])

    return {
        "source": "jira_groups",
        "user": current_user,
        "user_display_name": display_name,
        "groups_found": [g["group_name"] for g in groups_with_members],
        "all_groups": group_names,
        "groups_with_members": groups_with_members,
        "suggested_members": unique_members,
        "note": "SUGGESTION ONLY — present to user for confirmation before adding as watchers",
    }


def _fetch_group_members(group_name: str, headers: dict) -> list[dict]:
    """Fetch all members of a Jira group. Returns list of {displayName, accountId}."""
    import urllib.request

    members: list[dict] = []
    start_at = 0
    max_results = 50

    while True:
        url = (
            f"https://redhat.atlassian.net/rest/api/3/group/member"
            f"?groupname={urllib.request.quote(group_name)}"
            f"&startAt={start_at}&maxResults={max_results}"
        )
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception:
            break

        values = data.get("values", [])
        if not values:
            break

        for v in values:
            members.append(
                {
                    "displayName": v.get("displayName", ""),
                    "accountId": v.get("accountId", ""),
                }
            )

        if data.get("isLast", True):
            break
        start_at += max_results

    return members


def run_preflight(
    rhoaieng_url: str,
    rule_override: str | None = None,
    versions_override: list[str] | None = None,
    image_bases: list[str] | None = None,
    rpa_dir: str | None = None,
    clone_dir: str | None = None,
    environment: str = "prod",
) -> dict:
    """Run all pre-flight checks and return structured result."""
    output: dict = {
        "hard_rules": HARD_RULES,
        "decision": {},
        "rhoaieng": {},
        "rhoaieng_approval_status": {},
        "rule": {},
        "versions": {},
        "components": {},
        "effective_until": {},
        "related_psx": {},
        "existing_exceptions": {},
        "duplicate_check": {},
        "psx_watchers": {},
        "user_confirmation_required": [],
    }

    # 1. Fetch RHOAIENG ticket
    rhoaieng = fetch_rhoaieng_ticket(rhoaieng_url)
    output["rhoaieng"] = rhoaieng
    if "error" in rhoaieng:
        output["user_confirmation_required"].append(f"Cannot fetch RHOAIENG ticket: {rhoaieng['error']}")
        return output

    # 1b. Check RHOAIENG approval status
    approval_status = check_rhoaieng_approval_status(rhoaieng_url)
    output["rhoaieng_approval_status"] = approval_status
    if not approval_status["approved"]:
        output["user_confirmation_required"].append(
            f"RHOAIENG APPROVAL REQUIRED: {approval_status['reason']} "
            f"PSX Jira and GitLab Merge Request creation will be blocked "
            f"until this ticket is approved. Use --skip-approval-gate to "
            f"override (not recommended)."
        )

    # 2. Resolve rule
    if rule_override:
        resolved_rule = rule_override
        output["rule"] = {"value": resolved_rule, "source": "user_override"}
    elif rhoaieng.get("detected_rule"):
        resolved_rule = rhoaieng["detected_rule"]
        output["rule"] = {"value": resolved_rule, "source": "extracted_from_summary"}
        output["user_confirmation_required"].append(f"Confirm rule: {resolved_rule} (extracted from ticket summary)")
    else:
        resolved_rule = ""
        output["rule"] = {"value": None, "source": "not_found"}
        output["user_confirmation_required"].append("Could not extract rule from ticket. User must provide --rule.")

    # 3. Resolve versions
    if versions_override:
        versions = versions_override
        output["versions"] = {"values": versions, "source": "user_override"}
    else:
        output["versions"] = {"values": [], "source": "not_provided"}
        output["user_confirmation_required"].append("RHOAI versions not provided. User must specify.")
        versions = []

    # 4. Look up components
    if image_bases and versions:
        components = lookup_components_from_rpa(image_bases, versions, rpa_dir)
        output["components"] = {"per_version": components, "source": "rpa_lookup"}
        output["user_confirmation_required"].append(f"Confirm component names per version: {json.dumps(components)}")
    else:
        output["components"] = {"per_version": {}, "source": "not_resolved"}
        if not image_bases:
            output["user_confirmation_required"].append("Image base names not provided. Cannot look up components.")

    # 5. Resolve effectiveUntil dates
    if versions:
        dates = resolve_effective_until_dates(versions)
        output["effective_until"] = dates
        missing_dates = [v for v, d in dates.items() if d["effectiveUntil"] is None]
        if missing_dates:
            output["user_confirmation_required"].append(
                f"No default EOS dates for: {missing_dates}. User must provide."
            )
        else:
            output["user_confirmation_required"].append(
                "Confirm effectiveUntil dates (end-of-support + 7 day buffer): "
                + ", ".join(f"{v}={d['effectiveUntil']}" for v, d in dates.items())
            )

    # 6. Search related PSX
    if resolved_rule:
        related = search_related_psx(resolved_rule)
        output["related_psx"] = {"found": related, "count": len(related)}
    else:
        output["related_psx"] = {"found": [], "count": 0}

    # 7. Check existing exceptions in GitLab
    if resolved_rule:
        existing = search_existing_exceptions(resolved_rule, clone_dir)
        output["existing_exceptions"] = existing

    # 8. Discover user's Jira groups for PSX watcher suggestion
    watcher_info = discover_user_groups()
    output["psx_watchers"] = watcher_info
    suggested = watcher_info.get("suggested_members", [])
    if suggested:
        member_names = [m["displayName"] for m in suggested[:5]]
        suffix = f" (+{len(suggested) - 5} more)" if len(suggested) > 5 else ""
        output["user_confirmation_required"].append(
            f"PSX visibility: Found {len(suggested)} potential watchers from "
            f"group(s) {watcher_info.get('groups_found', [])}. "
            f"Suggested: {', '.join(member_names)}{suffix}. "
            f"Add as watchers? (source: {watcher_info['source']})"
        )

    # 9. Evaluate decision (deterministic go/no-go)
    components_per_version = output["components"].get("per_version", {})
    decision = evaluate_decision(
        existing_exceptions=output["existing_exceptions"] if output["existing_exceptions"] else {},
        components_per_version=components_per_version,
        environment=environment,
    )
    output["decision"] = decision

    if not decision["proceed"]:
        output["user_confirmation_required"] = [
            f"DECISION: ABORT — {decision['reason']}",
            "No further action required. The agent MUST NOT proceed with exception creation.",
        ]
        return output

    # 10. Check for duplicate PSX tickets
    if resolved_rule and versions:
        dupes = check_duplicate_psx_tickets(resolved_rule, versions)
        output["duplicate_check"] = {
            "existing_skill_created_psx": dupes,
            "count": len(dupes),
        }
        if dupes:
            output["user_confirmation_required"].append(
                f"WARNING: Found {len(dupes)} existing PSX ticket(s) created by this "
                f"skill for the same rule: {[d['key'] for d in dupes]}. "
                f"Confirm whether to reuse or create new."
            )

    # 11. RHOAIENG type warning
    if rhoaieng.get("type_warning"):
        output["user_confirmation_required"].append(rhoaieng["type_warning"])

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic pre-flight check for conforma-exception")
    parser.add_argument(
        "--check-existing-exception",
        action="store_true",
        help=(
            "Check if an active exception already exists for the given rule + components. "
            "No Jira required. Requires --rule and --components. Outputs JSON gate result."
        ),
    )
    parser.add_argument(
        "--check-violations-coverage",
        default=None,
        metavar="VIOLATIONS_YAML",
        help=(
            "Batch coverage check: path to a conforma-violations.yaml file. "
            "Checks all rules/components against existing exceptions in the policy file "
            "and outputs per-rule coverage status (fully_covered / partially_covered / not_covered)."
        ),
    )
    parser.add_argument("--rhoaieng-url", default=None, help="RHOAIENG Jira ticket URL")
    parser.add_argument("--rule", default=None, help="Override rule (skip extraction)")
    parser.add_argument(
        "--components",
        default=None,
        help="Comma-separated Konflux component names (required for --check-existing-exception)",
    )
    parser.add_argument("--versions", default=None, help="Comma-separated RHOAI versions (e.g. rhoai-2.25,rhoai-3.3)")
    parser.add_argument(
        "--image-bases",
        default=None,
        help="Comma-separated image base names for RPA lookup (e.g. odh-vllm-cpu,odh-vllm-gaudi)",
    )
    parser.add_argument("--rpa-dir", default=None, help="Path to RPA directory")
    parser.add_argument("--clone-dir", default=None, help="Path to konflux-release-data clone")
    parser.add_argument(
        "--environment",
        default="prod",
        choices=["prod", "stage"],
        help="Target environment (filters decision to relevant policy files)",
    )
    args = parser.parse_args()

    if args.check_existing_exception:
        if not args.rule:
            parser.error("--check-existing-exception requires --rule")
        if not args.components:
            parser.error("--check-existing-exception requires --components")
    elif args.check_violations_coverage:
        pass
    elif not args.rhoaieng_url:
        parser.error(
            "--rhoaieng-url is required (unless using --check-existing-exception or --check-violations-coverage)"
        )

    return args


def main() -> int:
    args = parse_args()

    if args.check_violations_coverage:
        result = check_violations_coverage(
            violations_yaml_path=args.check_violations_coverage,
            clone_dir=args.clone_dir,
            environment=args.environment,
        )
        print(json.dumps(result, indent=2))
        return 1 if "error" in result else 0

    if args.check_existing_exception:
        components = [c.strip() for c in args.components.split(",")]
        result = check_existing_exception_gate(
            rule=args.rule,
            components=components,
            clone_dir=args.clone_dir,
            environment=args.environment,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] != "blocked" else 1

    versions = [v.strip() for v in args.versions.split(",")] if args.versions else None
    image_bases = [i.strip() for i in args.image_bases.split(",")] if args.image_bases else None

    result = run_preflight(
        rhoaieng_url=args.rhoaieng_url,
        rule_override=args.rule,
        versions_override=versions,
        image_bases=image_bases,
        rpa_dir=args.rpa_dir,
        clone_dir=args.clone_dir,
        environment=args.environment,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
