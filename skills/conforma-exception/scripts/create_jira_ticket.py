#!/usr/bin/env python3
"""Create a Jira ticket for a Conforma exception request.

Supports three projects via --project flag:
  RHOAIENG  - blocker bug (approval) or bug (remediation)
  PSX       - PSRD Exception for security-related exceptions
  OCPEXCEPT - Task for FIPS-related exceptions

The --purpose flag differentiates RHOAIENG ticket types:
  approval    - Blocker Bug for exception approval (default)
  remediation - Bug assigned to devops/component team to fix the violation

All tickets receive:
  - A provenance label: conforma-exception-ai-skill
  - A provenance footer in the description

Usage:
  python3 create_jira_ticket.py --project RHOAIENG --purpose approval \
    --rule hermetic_task.hermetic --components odh-mlflow-v3-3 \
    --rhoai-version rhoai-3.3 --effective-until 2026-10-10T00:00:00Z \
    --template hermetic_build

  python3 create_jira_ticket.py --project RHOAIENG --purpose remediation \
    --rule hermetic_task.hermetic --components odh-mlflow-v3-3 \
    --rhoai-version rhoai-3.3 --effective-until 2026-10-10T00:00:00Z \
    --template hermetic_build --assignee "Component Team Lead"
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import getpass
import json
import os
import platform
import re
import sys
import tempfile
from pathlib import Path

import jira_ops
from add_jira_watchers import add_watchers_to_tickets as _add_jira_watchers
from cli_runner import _resolve_env, run_acli

TEMPLATE_TICKET = "RHOAIENG-62569"
PROVENANCE_REPO = "opendatahub-io/aiops-infra"
PROVENANCE_LABEL = "conforma-exception-ai-skill"
VIOLATION_LABEL = "conforma-violation"
VALID_PROJECTS = ("RHOAIENG", "PSX", "OCPEXCEPT")

PSX_MANDATORY_WATCHERS = ["Jay Koehler", "Lindani Phiri"]

MAX_VERIFY_RETRIES = 2

_TEMPLATES_FILE = Path(__file__).parent / "exception_templates.yaml"
_SKILL_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = _SKILL_DIR / ".work"


# ---------------------------------------------------------------------------
# Exception template loader
# ---------------------------------------------------------------------------


def _load_templates() -> dict:
    """Load exception_templates.yaml and return the parsed dict."""
    import yaml

    if not _TEMPLATES_FILE.is_file():
        raise FileNotFoundError(f"Template file not found: {_TEMPLATES_FILE}")
    with open(_TEMPLATES_FILE) as f:
        return yaml.safe_load(f)


def list_template_categories() -> list[dict]:
    """Return a list of available template categories with applicable justifications."""
    data = _load_templates()
    result = []
    for cat_id, cat in data.get("categories", {}).items():
        result.append({
            "id": cat_id,
            "display_name": cat["display_name"],
            "matches_rules": cat.get("matches_rules", []),
            "applicable_justifications": cat.get("applicable_justifications", []),
        })
    return result


def list_justifications() -> list[dict]:
    """Return a list of available justification templates."""
    data = _load_templates()
    result = []
    for j_id, j in data.get("justifications", {}).items():
        result.append({
            "id": j_id,
            "display_name": j.get("display_name", j_id),
        })
    return result


def match_template_category(rule: str) -> str | None:
    """Auto-detect the best template category for a given rule value.

    Tries specific categories first (via matches_rules globs). If none
    match, falls back to the 'other' catch-all category (if it exists).
    """
    import fnmatch

    data = _load_templates()
    for cat_id, cat in data.get("categories", {}).items():
        if cat.get("is_catch_all"):
            continue
        for pattern in cat.get("matches_rules", []):
            if fnmatch.fnmatch(rule, pattern):
                return cat_id

    if "other" in data.get("categories", {}):
        return "other"
    return None


def lookup_rule_in_catalog(rule: str) -> dict | None:
    """Look up a rule code in the Conforma release policy rules catalog.

    Returns a dict with 'code', 'name', and 'docs' if found, or None.
    Handles colon-suffixed rules (e.g. 'rpm_signature.allowed:abc123')
    by matching on the base code.
    """
    import yaml

    catalog_path = Path(__file__).resolve().parent.parent / "references" / "conforma-release-policy-rules.yaml"
    if not catalog_path.is_file():
        return None

    with open(catalog_path) as f:
        catalog = yaml.safe_load(f)

    base_rule = rule.split(":")[0] if ":" in rule else rule

    for entry in catalog.get("rules", []):
        if entry["code"] == base_rule or entry["code"] == rule:
            return entry
    return None


def resolve_template(
    category_id: str,
    variables: dict[str, str],
    justification_id: str | None = None,
) -> dict[str, str]:
    """Resolve template fields for a category+justification with the given variables.

    Category provides: summary_context, scope, impact, violation_summary.
    Justification provides: risk, remediation.

    The category's violation_summary is injected as {violation_summary} into the
    justification text before other variables are resolved.

    If justification_id is None, the first entry in applicable_justifications is used.

    Returns a dict with keys: summary_context, scope, risk, remediation, impact.
    """
    data = _load_templates()
    categories = data.get("categories", {})
    if category_id not in categories:
        raise ValueError(f"Unknown template category: {category_id}")
    cat = categories[category_id]

    applicable = cat.get("applicable_justifications", [])
    if justification_id is None and applicable:
        justification_id = applicable[0]

    justifications = data.get("justifications", {})

    result = {}
    for field in ("summary_context", "scope", "impact"):
        template_str = cat.get(field, "")
        try:
            result[field] = template_str.format_map(variables)
        except KeyError:
            result[field] = template_str

    violation_summary_raw = cat.get("violation_summary", "")
    try:
        violation_summary = violation_summary_raw.format_map(variables)
    except KeyError:
        violation_summary = violation_summary_raw

    just_vars = {**variables, "violation_summary": violation_summary}

    if justification_id and justification_id in justifications:
        just = justifications[justification_id]
        for field in ("risk", "remediation"):
            template_str = just.get(field, "")
            try:
                result[field] = template_str.format_map(just_vars)
            except KeyError:
                result[field] = template_str
    else:
        result["risk"] = ""
        result["remediation"] = ""

    return result


# ---------------------------------------------------------------------------
# Credential bridging
# ---------------------------------------------------------------------------


def _ensure_jira_env() -> None:
    """Bridge conforma token discovery to env vars for jira_ops."""
    if not os.environ.get("JIRA_API_TOKEN"):
        token = _resolve_env("JIRA_API_TOKEN")
        if token:
            os.environ["JIRA_API_TOKEN"] = token
    if not os.environ.get("JIRA_EMAIL"):
        email = _resolve_env("JIRA_EMAIL")
        if email:
            os.environ["JIRA_EMAIL"] = email


# ---------------------------------------------------------------------------
# REST API helpers
# ---------------------------------------------------------------------------


def _jira_auth() -> tuple[str, str] | None:
    """Return (email, base64-encoded auth header value) or None if not configured."""
    import base64

    token = _resolve_env("JIRA_API_TOKEN") or ""
    email = _resolve_env("JIRA_EMAIL") or ""
    if not token or not email:
        return None
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    return email, auth


def _jira_rest_get(
    path: str, fields: str | None = None
) -> dict | None:
    """GET a Jira REST API endpoint. Returns parsed JSON or None on failure."""
    import urllib.request

    creds = _jira_auth()
    if not creds:
        return None
    _, auth = creds

    url = f"https://redhat.atlassian.net/rest/api/3/{path}"
    if fields:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}fields={fields}"

    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _jira_rest_put(path: str, payload: dict) -> dict:
    """PUT to a Jira REST API endpoint. Returns {ok: bool, status: int, error: str}."""
    import urllib.error
    import urllib.request

    creds = _jira_auth()
    if not creds:
        return {"ok": False, "status": 0, "error": "JIRA_API_TOKEN/EMAIL not configured"}
    _, auth = creds

    url = f"https://redhat.atlassian.net/rest/api/3/{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return {"ok": resp.status in (200, 204), "status": resp.status, "error": ""}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# Verification contract
# ---------------------------------------------------------------------------


def _verify_ticket_state(
    ticket_key: str,
    expected_summary: str | None = None,
    expected_labels: list[str] | None = None,
    expected_links: list[str] | None = None,
    expected_description_min_nodes: int | None = None,
    expected_authorized_party: bool = False,
) -> dict:
    """Read ticket via REST API and verify all expected fields.

    Returns:
        {
            "verified": bool,
            "checks": [{"field": str, "expected": str, "actual": str, "ok": bool}],
            "unmet": [str],  # human-readable list of unmet expectations
        }
    """
    checks: list[dict] = []
    unmet: list[str] = []

    data = _jira_rest_get(
        f"issue/{ticket_key}",
        fields="summary,labels,issuelinks,description,customfield_10938",
    )
    if not data:
        return {
            "verified": False,
            "checks": [],
            "unmet": [f"Cannot read {ticket_key} via REST API"],
        }

    fields = data.get("fields", {})

    if expected_summary:
        actual = fields.get("summary", "")
        ok = expected_summary in actual or actual == expected_summary
        checks.append({
            "field": "summary", "expected": expected_summary,
            "actual": actual, "ok": ok,
        })
        if not ok:
            unmet.append(f"summary mismatch: expected contains '{expected_summary}'")

    if expected_labels:
        actual_labels = fields.get("labels", [])
        missing = [l for l in expected_labels if l not in actual_labels]
        ok = len(missing) == 0
        checks.append({
            "field": "labels", "expected": expected_labels,
            "actual": actual_labels, "ok": ok,
        })
        if not ok:
            unmet.append(f"labels missing: {missing}")

    if expected_links:
        actual_links_raw = fields.get("issuelinks", [])
        actual_keys = set()
        for link in actual_links_raw:
            k = link.get("inwardIssue", {}).get("key", "")
            if k:
                actual_keys.add(k)
            k = link.get("outwardIssue", {}).get("key", "")
            if k:
                actual_keys.add(k)
        missing_links = [l for l in expected_links if l not in actual_keys]
        ok = len(missing_links) == 0
        checks.append({
            "field": "issuelinks", "expected": expected_links,
            "actual": list(actual_keys), "ok": ok,
        })
        if not ok:
            unmet.append(f"links missing: {missing_links}")

    if expected_description_min_nodes is not None:
        desc = fields.get("description", {})
        node_count = len(desc.get("content", [])) if isinstance(desc, dict) else 0
        ok = node_count >= expected_description_min_nodes
        checks.append({
            "field": "description_nodes",
            "expected": f">= {expected_description_min_nodes}",
            "actual": node_count, "ok": ok,
        })
        if not ok:
            unmet.append(
                f"description has {node_count} nodes, "
                f"expected >= {expected_description_min_nodes}"
            )

    if expected_authorized_party:
        ap = fields.get("customfield_10938")
        ok = ap is not None and ap != ""
        checks.append({
            "field": "customfield_10938",
            "expected": "set",
            "actual": ap.get("displayName", "") if isinstance(ap, dict) else str(ap),
            "ok": ok,
        })
        if not ok:
            unmet.append("authorized_party (customfield_10938) not set")

    return {
        "verified": len(unmet) == 0,
        "checks": checks,
        "unmet": unmet,
    }


def build_provenance_footer() -> str:
    """Standard provenance footer for all tickets and comments."""
    return (
        "---\n"
        f"Created by 'conforma-exception' skill from {PROVENANCE_REPO}\n"
        f"User: {getpass.getuser()}@{platform.node()}"
    )


def fetch_template_description() -> str:
    """Fetch the description of the RHOAIENG template ticket via acli."""
    result = run_acli(
        ["jira", "workitem", "view", TEMPLATE_TICKET, "--json"],
        timeout=30,
    )
    if result.returncode != 0:
        print(
            f"Error: Failed to fetch template {TEMPLATE_TICKET}: {result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        ticket_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(
            f"Error: Invalid JSON from acli for {TEMPLATE_TICKET}",
            file=sys.stderr,
        )
        sys.exit(1)

    description = ticket_data.get("description", "")
    if not description:
        description = ticket_data.get("fields", {}).get("description", "")
    return description if isinstance(description, str) else json.dumps(description)


def build_exception_label(rule: str, components: list[str]) -> str:
    """Build the exception label: Exception - <rule>:<first-component>."""
    component_ref = components[0] if components else "unknown"
    return f"Exception - {rule}:{component_ref}"


def _build_rhoaieng_description(
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    psx_url: str | None,
    exception_scope: str | None = None,
    exception_risk: str | None = None,
    exception_remediation: str | None = None,
) -> dict:
    """Build ADF description for RHOAIENG approval ticket."""
    context_text = (
        f"Exception Request Details\n\n"
        f"Rule: {rule}\n"
        f"Components: {', '.join(components)}\n"
        f"RHOAI Version: {rhoai_version}\n"
        f"Effective Until: {effective_until}\n"
    )
    if exception_scope:
        context_text += f"\nScope: {exception_scope}\n"
    if exception_risk:
        context_text += f"\nRisk: {exception_risk}\n"
    if exception_remediation:
        context_text += f"\nRemediation: {exception_remediation}\n"
    if psx_url:
        context_text += f"\nPSX/OCPEXCEPT Ticket: {psx_url}\n"

    context_text += f"\n{build_provenance_footer()}"

    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": context_text}],
            },
        ],
    }


def _build_rhoaieng_remediation_description(
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    rhoaieng_approval_url: str | None,
    exception_scope: str | None = None,
    exception_remediation: str | None = None,
) -> dict:
    """Build ADF description for RHOAIENG remediation ticket."""
    context_text = (
        f"Remediation Required\n\n"
        f"This ticket tracks the fix for the following Conforma violation.\n\n"
        f"Rule: {rule}\n"
        f"Components: {', '.join(components)}\n"
        f"RHOAI Version: {rhoai_version}\n"
        f"Exception Effective Until: {effective_until}\n"
    )
    if exception_scope:
        context_text += f"\nScope: {exception_scope}\n"
    if exception_remediation:
        context_text += f"\nRemediation: {exception_remediation}\n"
    if rhoaieng_approval_url:
        context_text += f"\nApproval Ticket: {rhoaieng_approval_url}\n"

    context_text += f"\n{build_provenance_footer()}"

    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": context_text}],
            },
        ],
    }


def _build_psx_description(
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    rhoaieng_url: str,
) -> dict:
    """Build minimal ADF description for PSX/OCPEXCEPT ticket creation.

    This is used at creation time. The server may apply its own template,
    so _fill_psx_template() is called after creation to fill in the real content.
    """
    context_text = (
        f"Conforma Exception Request\n\n"
        f"Rule: {rule}\n"
        f"Components: {', '.join(components)}\n"
        f"RHOAI Version: {rhoai_version}\n"
        f"RHOAIENG Ticket: {rhoaieng_url}\n"
    )
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": context_text}],
            },
        ],
    }


def _build_psx_filled_adf(
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    rhoaieng_url: str,
    exception_scope: str | None = None,
    exception_risk: str | None = None,
    exception_remediation: str | None = None,
    exception_impact: str | None = None,
) -> dict:
    """Build proper ADF for PSX description matching the server-side template structure.

    The PSX project uses info panels as section headers with answer paragraphs below.
    This produces the same visual structure as PSX-1042 and other correctly-filled tickets.
    """
    components_text = ", ".join(components)
    scope = exception_scope or f"Affected RHOAI container components: {components_text}"
    risk = exception_risk or (
        f"The affected RHOAI versions have already been released or are in "
        f"code-freeze, therefore the violation cannot be fixed retroactively."
    )
    remediation = exception_remediation or (
        f"Grant Conforma exception for {rule} for affected "
        f"components for the duration of {rhoai_version} support lifecycle. "
        f"For future RHOAI releases, the exception will be requested as "
        f"part of the release exception MR process if the violation persists."
    )
    impact = exception_impact or (
        f"Without this exception, Conforma will block release pipeline gates "
        f"for {rhoai_version}. This would prevent z-stream security fixes "
        f"from shipping."
    )

    def _panel(text: str) -> dict:
        return {
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]}
            ],
        }

    def _para(text: str) -> dict:
        return {"type": "paragraph", "content": [{"type": "text", "text": text}]}

    def _spacer() -> dict:
        return {"type": "paragraph", "content": [{"type": "text", "text": " "}]}

    reason_text = (
        f"Conforma policy rule: {rule}\n"
        f"Components: {components_text}\n"
        f"RHOAI Version(s): {rhoai_version}\n"
        f"effectiveUntil: {effective_until}\n\n"
        f"This exception is required because {rhoai_version} has already "
        f"been released/code-frozen and major build infrastructure changes "
        f"are not permitted in z-stream/sub-releases.\n\n"
        f"Scope: {scope}\n\n"
        f"RHOAIENG tracking ticket: {rhoaieng_url}\n\n"
        f"Note: it is not possible to add new signing keys to the global "
        f"Conforma allowed list. Exceptions via the per-component MR process "
        f"are the only path for third-party signed RPMs."
    )

    provenance = build_provenance_footer()

    content = [
        _panel("Note: Important Dates (Jira fields)"),
        _para(f"Due Date: {effective_until}"),
        _spacer(),
        _panel(
            "What is the reason for the exception?\n"
            "Provide a detailed description explaining why the exception is needed."
        ),
        _para(reason_text),
        _spacer(),
        _panel(
            "Risk if we approve the exception?\n"
            "What risk is being accepted by approving this exception?"
        ),
        _para(risk),
        _spacer(),
        _panel(
            "Impact of NOT approving the exception?\n"
            "Provide details on the impact that not approving this exception will have."
        ),
        _para(impact),
        _spacer(),
        _panel(
            "Proposed remediation\n"
            "Provide a detailed description of the proposed plan to complete this work."
        ),
        _para(remediation),
        _spacer(),
        _panel("SME / Validator Notes (ProdSec Only) (Optional)"),
        _para(""),
        _spacer(),
        _para(provenance),
    ]

    return {"version": 1, "type": "doc", "content": content}


def _set_authorized_party_field(ticket_key: str, authorized_party: str) -> dict:
    """Set the Authorized Party user picker field (customfield_10938) via REST API.

    Searches for the user via jira_ops.search_user(), then sets the field.
    Falls back to raw REST user search if jira_ops fails.
    Returns structured dict with operation details.
    """
    _ensure_jira_env()
    account_id = None
    matched_name = None

    try:
        result = jira_ops.search_user(authorized_party)
        if result.get("found"):
            account_id = result["account_id"]
            matched_name = result["display_name"]
    except Exception:
        pass

    if not account_id:
        import urllib.request

        creds = _jira_auth()
        if not creds:
            return {
                "ok": False, "action": "set_authorized_party",
                "error": "JIRA auth not configured",
            }
        _, auth = creds

        search_url = (
            f"https://redhat.atlassian.net/rest/api/3/user/search"
            f"?query={urllib.request.quote(authorized_party)}&maxResults=5"
        )
        req = urllib.request.Request(search_url, headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                users = json.loads(resp.read())
        except Exception as e:
            return {
                "ok": False, "action": "set_authorized_party",
                "error": f"user search failed: {e}",
            }

        for user in users:
            if user.get("displayName", "").lower() == authorized_party.lower():
                account_id = user["accountId"]
                matched_name = user.get("displayName", "")
                break
        if not account_id and users:
            account_id = users[0]["accountId"]
            matched_name = users[0].get("displayName", "")

    if not account_id:
        return {
            "ok": False, "action": "set_authorized_party",
            "error": f"user '{authorized_party}' not found (0 results)",
        }

    put_result = _jira_rest_put(
        f"issue/{ticket_key}",
        {"fields": {"customfield_10938": {"accountId": account_id}}},
    )
    return {
        "ok": put_result["ok"],
        "action": "set_authorized_party",
        "ticket_key": ticket_key,
        "user_matched": matched_name,
        "account_id": account_id,
        "error": put_result.get("error", ""),
    }


def _fill_psx_template(
    ticket_key: str,
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    rhoaieng_url: str,
    exception_scope: str | None = None,
    exception_risk: str | None = None,
    exception_remediation: str | None = None,
    exception_impact: str | None = None,
    authorized_party: str | None = None,
) -> dict:
    """Fill the PSX ticket description with proper ADF content via REST API.

    The PSX project applies a server-side template for PSRD Exception tickets.
    This function waits briefly, then overwrites with properly-structured ADF
    (info panels + answer paragraphs) matching the template's visual format.
    Also sets the Authorized Party user picker field if provided.

    Returns structured dict with operation results.
    """
    import time

    time.sleep(3)

    ap_set = False
    if authorized_party:
        ap_result = _set_authorized_party_field(ticket_key, authorized_party)
        ap_set = ap_result.get("ok", False)

    adf = _build_psx_filled_adf(
        rule, components, rhoai_version, effective_until,
        rhoaieng_url, exception_scope=exception_scope, exception_risk=exception_risk,
        exception_remediation=exception_remediation, exception_impact=exception_impact,
    )

    desc_result = _jira_rest_put(
        f"issue/{ticket_key}", {"fields": {"description": adf}}
    )

    return {
        "action": "fill_psx_template",
        "ok": desc_result["ok"],
        "ticket_key": ticket_key,
        "description_status": desc_result.get("status", 0),
        "description_error": desc_result.get("error", ""),
        "authorized_party_set": ap_set,
    }


def create_ticket(
    project: str,
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    rhoaieng_url: str | None = None,
    psx_url: str | None = None,
    link_to: str | None = None,
    summary_context: str | None = None,
    vendor_tag: str | None = None,
    exception_scope: str | None = None,
    exception_risk: str | None = None,
    exception_remediation: str | None = None,
    exception_impact: str | None = None,
    authorized_party: str | None = None,
    watcher_names: list[str] | None = None,
    purpose: str = "approval",
    assignee: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Create a Jira ticket in the specified project.

    For RHOAIENG tickets, purpose controls the ticket type:
      - "approval": Blocker Bug for exception approval
      - "remediation": Bug for tracking the fix
    """
    if project not in VALID_PROJECTS:
        return {
            "status": "failed",
            "error": f"Invalid project: {project}. Must be one of {VALID_PROJECTS}",
            "project": project,
            "ticket_key": None,
            "ticket_url": None,
        }

    tag_prefix = f"[{vendor_tag}] " if vendor_tag else ""
    purpose_tag = "[Remediation] " if purpose == "remediation" else "[Conforma Exception] "
    if summary_context:
        summary = f"{tag_prefix}{purpose_tag}{rule} - {rhoai_version} - {summary_context}"
    else:
        summary = f"{tag_prefix}{purpose_tag}{rule} - {rhoai_version}"
    labels = [PROVENANCE_LABEL, VIOLATION_LABEL]

    if project == "RHOAIENG" and purpose == "remediation":
        exception_label = build_exception_label(rule, components)
        labels.append(exception_label)
        description_adf = _build_rhoaieng_remediation_description(
            rule, components, rhoai_version, effective_until, rhoaieng_url,
            exception_scope=exception_scope, exception_remediation=exception_remediation,
        )
        issue_json: dict = {
            "projectKey": project,
            "summary": summary,
            "type": "Bug",
            "description": description_adf,
            "additionalAttributes": {
                "labels": labels,
            },
        }
    elif project == "RHOAIENG":
        fetch_template_description()
        exception_label = build_exception_label(rule, components)
        labels.append(exception_label)
        description_adf = _build_rhoaieng_description(
            rule, components, rhoai_version, effective_until, psx_url,
            exception_scope=exception_scope, exception_risk=exception_risk,
            exception_remediation=exception_remediation,
        )
        issue_json = {
            "projectKey": project,
            "summary": summary,
            "type": "Bug",
            "priority": "Blocker",
            "description": description_adf,
            "additionalAttributes": {
                "labels": labels,
            },
        }
    elif project == "PSX":
        description_adf = _build_psx_description(
            rule,
            components,
            rhoai_version,
            effective_until,
            rhoaieng_url or "",
        )
        issue_json = {
            "projectKey": project,
            "summary": summary,
            "type": "PSRD Exception",
            "description": description_adf,
            "additionalAttributes": {
                "labels": labels,
            },
        }
    else:  # OCPEXCEPT
        description_adf = _build_psx_description(
            rule,
            components,
            rhoai_version,
            effective_until,
            rhoaieng_url or "",
        )
        issue_json = {
            "projectKey": project,
            "summary": summary,
            "type": "Task",
            "description": description_adf,
            "additionalAttributes": {
                "labels": labels,
            },
        }

    if dry_run:
        return {
            "status": "dry_run",
            "project": project,
            "ticket_key": None,
            "ticket_url": None,
            "summary": summary,
            "labels": labels,
            "issue_json": issue_json,
        }

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix=f"{project.lower()}-create-", delete=False,
        dir=WORK_DIR,
    )
    try:
        json.dump(issue_json, tmp, indent=2)
        tmp.close()

        result = run_acli(
            ["jira", "workitem", "create", "--from-json", tmp.name],
            timeout=30,
        )
        if result.returncode != 0:
            return {
                "status": "failed",
                "project": project,
                "error": result.stderr.strip() or result.stdout.strip(),
                "ticket_key": None,
                "ticket_url": None,
            }

        output = result.stdout.strip()
        ticket_key = _extract_ticket_key(output, project)
        ticket_url = f"https://redhat.atlassian.net/browse/{ticket_key}" if ticket_key else None

        # --- Post-creation: apply all fields with retry ---
        if ticket_key:
            apply_result = _apply_and_verify(
                ticket_key=ticket_key,
                project=project,
                summary=summary,
                labels=labels,
                rhoaieng_url=rhoaieng_url,
                psx_url=psx_url,
                link_to=link_to,
                rule=rule,
                components=components,
                rhoai_version=rhoai_version,
                effective_until=effective_until,
                exception_scope=exception_scope,
                exception_risk=exception_risk,
                exception_remediation=exception_remediation,
                exception_impact=exception_impact,
                authorized_party=authorized_party,
            )
        else:
            apply_result = {"operations": [], "verification": None}

        # --- Post-creation: add watchers ---
        # For PSX/OCPEXCEPT, mandatory watchers are always prepended.
        # Team members should already be included in watcher_names by the
        # agent after running discover_team() and getting user confirmation
        # during the questionnaire (Batch 3, item 10).
        watcher_result = None
        if ticket_key:
            is_psx = project in ("PSX", "OCPEXCEPT")
            all_watchers = list(PSX_MANDATORY_WATCHERS) if is_psx else []
            if watcher_names:
                for name in watcher_names:
                    if name not in all_watchers:
                        all_watchers.append(name)
            if all_watchers:
                batch = _add_jira_watchers([ticket_key], all_watchers)
                watcher_result = batch.get("tickets", [None])[0]
                if watcher_result:
                    apply_result.setdefault("operations", []).append(watcher_result)

        return {
            "status": "created",
            "project": project,
            "ticket_key": ticket_key,
            "ticket_url": ticket_url,
            "summary": summary,
            "labels": labels,
            "linked_to": apply_result.get("linked_to", []),
            "description_filled": apply_result.get("description_filled", False),
            "authorized_party_set": apply_result.get(
                "authorized_party_set", False
            ),
            "watchers": watcher_result,
            "verification": apply_result.get("verification"),
            "operations": apply_result.get("operations", []),
            "raw_output": output,
        }
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _set_labels_rest(ticket_key: str, labels: list[str]) -> dict:
    """Set labels on a ticket via REST API PUT (replaces all labels).

    Returns structured result with operation status.
    """
    data = _jira_rest_get(f"issue/{ticket_key}", fields="labels")
    if not data:
        return {"ok": False, "action": "set_labels", "error": "cannot read ticket"}

    existing = data.get("fields", {}).get("labels", [])
    all_labels = list(set(existing + labels))

    result = _jira_rest_put(
        f"issue/{ticket_key}", {"fields": {"labels": all_labels}}
    )
    return {
        "ok": result["ok"],
        "action": "set_labels",
        "ticket_key": ticket_key,
        "labels_set": all_labels,
        "error": result.get("error", ""),
    }


def _enforce_labels(ticket_key: str, required_labels: list[str]) -> dict:
    """Verify labels are on the ticket. If missing, set them via REST API.

    Returns structured dict with what was attempted and the result.
    """
    data = _jira_rest_get(f"issue/{ticket_key}", fields="labels")
    existing: list[str] = []
    if data:
        existing = data.get("fields", {}).get("labels", [])

    missing = [lbl for lbl in required_labels if lbl not in existing]
    if not missing:
        return {
            "ok": True, "action": "enforce_labels",
            "ticket_key": ticket_key, "already_present": True,
        }

    all_labels = list(set(existing + required_labels))
    put_result = _jira_rest_put(
        f"issue/{ticket_key}", {"fields": {"labels": all_labels}}
    )

    if not put_result["ok"]:
        edit_result = run_acli(
            ["jira", "workitem", "edit", "--key", ticket_key,
             "--labels", ",".join(all_labels), "--yes"],
            timeout=30,
        )
        return {
            "ok": edit_result.returncode == 0,
            "action": "enforce_labels",
            "ticket_key": ticket_key,
            "method": "acli_fallback",
            "error": "" if edit_result.returncode == 0 else edit_result.stderr.strip(),
        }

    return {
        "ok": True, "action": "enforce_labels",
        "ticket_key": ticket_key, "method": "rest_api",
        "labels_set": all_labels,
    }


def _verify_link_exists(ticket_key: str, target_key: str) -> bool:
    """Verify a link exists between ticket_key and target_key via REST API."""
    data = _jira_rest_get(f"issue/{ticket_key}", fields="issuelinks")
    if not data:
        return True  # Can't verify, assume success

    links = data.get("fields", {}).get("issuelinks", [])
    for link in links:
        inward = link.get("inwardIssue", {}).get("key", "")
        outward = link.get("outwardIssue", {}).get("key", "")
        if target_key in (inward, outward):
            return True
    return False


def _apply_and_verify(
    ticket_key: str,
    project: str,
    summary: str,
    labels: list[str],
    rhoaieng_url: str | None,
    psx_url: str | None,
    link_to: str | None,
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    exception_scope: str | None = None,
    exception_risk: str | None = None,
    exception_remediation: str | None = None,
    exception_impact: str | None = None,
    authorized_party: str | None = None,
) -> dict:
    """Apply all post-creation mutations and verify the final state.

    Orchestrates: labels, links, description, authorized party.
    Retries failed operations up to MAX_VERIFY_RETRIES times.
    Returns structured result with operations log and verification outcome.
    """
    operations: list[dict] = []
    linked_to: list[str] = []
    description_filled = False
    authorized_party_set = False

    # --- Step 1: Enforce labels via REST ---
    label_result = _enforce_labels(ticket_key, labels)
    operations.append(label_result)

    # --- Step 2: Create links ---
    expected_links: list[str] = []
    link_target = _resolve_link_target(project, rhoaieng_url, psx_url)
    if link_target:
        expected_links.append(link_target)
        ok = _link_tickets(ticket_key, link_target)
        operations.append({
            "action": "link_create", "from": ticket_key,
            "to": link_target, "ok": ok,
        })
        if ok:
            linked_to.append(link_target)

    if link_to:
        expected_links.append(link_to)
        ok = _link_tickets(ticket_key, link_to)
        operations.append({
            "action": "link_create", "from": ticket_key,
            "to": link_to, "ok": ok,
        })
        if ok:
            linked_to.append(link_to)

    # --- Step 3: Fill PSX/OCPEXCEPT description + authorized party ---
    if project in ("PSX", "OCPEXCEPT"):
        desc_result = _fill_psx_template(
            ticket_key, rule, components,
            rhoai_version, effective_until, rhoaieng_url or "",
            exception_scope=exception_scope, exception_risk=exception_risk,
            exception_remediation=exception_remediation, exception_impact=exception_impact,
            authorized_party=authorized_party,
        )
        description_filled = desc_result.get("ok", False)
        authorized_party_set = desc_result.get("authorized_party_set", False)
        operations.append(desc_result)

    # --- Step 4: Verify final state ---
    verification = _verify_ticket_state(
        ticket_key,
        expected_labels=labels,
        expected_links=expected_links if expected_links else None,
        expected_description_min_nodes=15 if project in ("PSX", "OCPEXCEPT") else None,
        expected_authorized_party=bool(authorized_party),
    )

    # --- Step 5: Retry unmet expectations ---
    if not verification["verified"]:
        for attempt in range(MAX_VERIFY_RETRIES):
            for issue in verification["unmet"]:
                if "labels missing" in issue:
                    r = _enforce_labels(ticket_key, labels)
                    operations.append({**r, "retry": attempt + 1})
                elif "links missing" in issue:
                    for lk in expected_links:
                        if not _verify_link_exists(ticket_key, lk):
                            ok = _link_tickets(ticket_key, lk)
                            operations.append({
                                "action": "link_retry", "to": lk,
                                "ok": ok, "retry": attempt + 1,
                            })
                elif "authorized_party" in issue and authorized_party:
                    _set_authorized_party_field(ticket_key, authorized_party)
                    operations.append({
                        "action": "set_authorized_party_retry",
                        "retry": attempt + 1,
                    })
                elif "description" in issue and project in ("PSX", "OCPEXCEPT"):
                    desc_r = _fill_psx_template(
                        ticket_key, rule, components,
                        rhoai_version, effective_until, rhoaieng_url or "",
                        exception_scope=exception_scope, exception_risk=exception_risk,
                        exception_remediation=exception_remediation,
                        exception_impact=exception_impact,
                        authorized_party=authorized_party,
                    )
                    operations.append({
                        "action": "fill_description_retry",
                        "ok": desc_r.get("ok", False),
                        "retry": attempt + 1,
                    })

            import time
            time.sleep(2)
            verification = _verify_ticket_state(
                ticket_key,
                expected_labels=labels,
                expected_links=expected_links if expected_links else None,
                expected_description_min_nodes=(
                    15 if project in ("PSX", "OCPEXCEPT") else None
                ),
                expected_authorized_party=bool(authorized_party),
            )
            if verification["verified"]:
                break

    return {
        "linked_to": linked_to,
        "description_filled": description_filled,
        "authorized_party_set": authorized_party_set,
        "operations": operations,
        "verification": verification,
    }


def _resolve_link_target(project: str, rhoaieng_url: str | None, psx_url: str | None) -> str | None:
    """Determine which ticket to link the newly created one to.

    PSX/OCPEXCEPT tickets link to the RHOAIENG ticket.
    RHOAIENG tickets link to the PSX ticket if available.
    """
    if project in ("PSX", "OCPEXCEPT") and rhoaieng_url:
        return _extract_key_from_url(rhoaieng_url)
    if project == "RHOAIENG" and psx_url:
        return _extract_key_from_url(psx_url)
    return None


def _link_tickets(from_key: str, to_key: str, link_type: str = "Related") -> bool:
    """Create a link between two Jira tickets. Returns True on success.

    Uses jira_ops.link_issues() (python-jira library) with acli fallback.
    """
    _ensure_jira_env()
    link_result = jira_ops.link_issues(from_key, to_key, link_type=link_type)
    if link_result.get("ok"):
        return True

    result = run_acli(
        [
            "jira", "workitem", "link", "create",
            "--out", from_key, "--in", to_key,
            "--type", link_type, "--yes",
        ],
        timeout=30,
    )
    return result.returncode == 0


def _delete_link(ticket_key: str, target_key: str, link_type: str | None = None) -> bool:
    """Delete a link between two Jira tickets by finding its ID via REST API.

    acli link delete requires --id (numeric), not --out/--in/--type.
    This function fetches links via REST, finds the matching one, and deletes by ID.

    Args:
        ticket_key: The ticket to look up links on.
        target_key: The linked ticket to find and remove.
        link_type: Optional link type name to match (e.g. 'Related', 'Blocks').
                   If None, deletes ANY link to target_key.
    """
    import base64
    import urllib.request

    from cli_runner import _resolve_env

    token = _resolve_env("JIRA_API_TOKEN") or ""
    email = _resolve_env("JIRA_EMAIL") or ""
    if not token or not email:
        return False

    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    url = f"https://redhat.atlassian.net/rest/api/3/issue/{ticket_key}?fields=issuelinks"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return False

    links = data.get("fields", {}).get("issuelinks", [])
    for link in links:
        inward = link.get("inwardIssue", {}).get("key", "")
        outward = link.get("outwardIssue", {}).get("key", "")
        lt_name = link.get("type", {}).get("name", "")
        link_id = link.get("id")

        if target_key not in (inward, outward):
            continue
        if link_type and lt_name != link_type:
            continue

        result = run_acli(
            ["jira", "workitem", "link", "delete", "--id", str(link_id), "--yes"],
            timeout=30,
        )
        return result.returncode == 0

    return False


def _extract_ticket_key(output: str, project: str) -> str | None:
    """Extract ticket key from acli output."""
    match = re.search(rf"({re.escape(project)}-\d+)", output)
    return match.group(1) if match else None


def _extract_key_from_url(url: str) -> str | None:
    """Extract Jira ticket key from a URL."""
    match = re.search(r"([A-Z]+-\d+)", url)
    return match.group(1) if match else None


def reconcile_ticket(
    ticket_key: str,
    project: str,
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    rhoaieng_url: str | None = None,
    psx_url: str | None = None,
    link_to: str | None = None,
    summary_context: str | None = None,
    vendor_tag: str | None = None,
    exception_scope: str | None = None,
    exception_risk: str | None = None,
    exception_remediation: str | None = None,
    exception_impact: str | None = None,
    authorized_party: str | None = None,
) -> dict:
    """Reconcile an existing ticket to match expected state.

    Reads the ticket, computes what's missing, applies only the needed changes,
    and verifies the final state. Idempotent -- safe to re-run.
    """
    data = _jira_rest_get(
        f"issue/{ticket_key}",
        fields="summary,labels,issuelinks,description,customfield_10938",
    )
    if not data:
        return {
            "status": "failed",
            "ticket_key": ticket_key,
            "error": f"Cannot read {ticket_key} via REST API -- check auth",
        }

    fields = data.get("fields", {})
    operations: list[dict] = []

    # Build expected summary for reference
    summary = _build_summary(
        project, rule, components, rhoai_version,
        summary_context, vendor_tag,
    )

    # Determine expected labels
    labels = [PROVENANCE_LABEL, VIOLATION_LABEL]
    if rule:
        labels.append(f"Exception:{rule}")

    # --- Reconcile labels ---
    existing_labels = fields.get("labels", [])
    missing_labels = [l for l in labels if l not in existing_labels]
    if missing_labels:
        r = _enforce_labels(ticket_key, labels)
        operations.append(r)

    # --- Reconcile links ---
    expected_links: list[str] = []
    link_target = _resolve_link_target(project, rhoaieng_url, psx_url)
    if link_target:
        expected_links.append(link_target)
    if link_to:
        expected_links.append(link_to)

    if expected_links:
        actual_keys: set[str] = set()
        for link in fields.get("issuelinks", []):
            k = link.get("inwardIssue", {}).get("key", "")
            if k:
                actual_keys.add(k)
            k = link.get("outwardIssue", {}).get("key", "")
            if k:
                actual_keys.add(k)
        for target in expected_links:
            if target not in actual_keys:
                ok = _link_tickets(ticket_key, target)
                operations.append({
                    "action": "link_create", "from": ticket_key,
                    "to": target, "ok": ok,
                })

    # --- Reconcile description (PSX/OCPEXCEPT only) ---
    description_filled = False
    if project in ("PSX", "OCPEXCEPT"):
        desc = fields.get("description", {})
        node_count = len(desc.get("content", [])) if isinstance(desc, dict) else 0
        if node_count < 15:
            desc_result = _fill_psx_template(
                ticket_key, rule, components,
                rhoai_version, effective_until, rhoaieng_url or "",
                exception_scope=exception_scope, exception_risk=exception_risk,
                exception_remediation=exception_remediation, exception_impact=exception_impact,
                authorized_party=authorized_party,
            )
            description_filled = desc_result.get("ok", False)
            operations.append(desc_result)
        else:
            description_filled = True

    # --- Reconcile authorized party ---
    authorized_party_set = False
    if authorized_party:
        ap_val = fields.get("customfield_10938")
        if not ap_val:
            ap_result = _set_authorized_party_field(ticket_key, authorized_party)
            operations.append(ap_result)
            authorized_party_set = ap_result.get("ok", False)
        else:
            authorized_party_set = True

    # --- Final verification ---
    verification = _verify_ticket_state(
        ticket_key,
        expected_labels=labels,
        expected_links=expected_links if expected_links else None,
        expected_description_min_nodes=15 if project in ("PSX", "OCPEXCEPT") else None,
        expected_authorized_party=bool(authorized_party),
    )

    return {
        "status": "reconciled" if verification["verified"] else "partial",
        "ticket_key": ticket_key,
        "ticket_url": f"https://redhat.atlassian.net/browse/{ticket_key}",
        "operations": operations,
        "verification": verification,
        "description_filled": description_filled,
        "authorized_party_set": authorized_party_set,
    }


def _build_summary(
    project: str, rule: str, components: list[str],
    rhoai_version: str, summary_context: str | None,
    vendor_tag: str | None,
) -> str:
    """Build the expected summary string for a ticket."""
    comp_str = ", ".join(components[:3])
    if len(components) > 3:
        comp_str += f" (+{len(components) - 3} more)"
    base = f"[Conforma Exception] {rule} - {rhoai_version} - {comp_str}"
    if summary_context:
        base = f"{base} - {summary_context}"
    if vendor_tag:
        base = f"[{vendor_tag}] {base}"
    return base


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Jira ticket for Conforma exception")
    parser.add_argument(
        "--project",
        required=True,
        choices=VALID_PROJECTS,
        help="Target Jira project",
    )
    parser.add_argument("--rule", required=True)
    parser.add_argument("--components", required=True, help="Comma-separated")
    parser.add_argument("--justification", default=None,
                        help="Justification template ID (e.g., dev_preview, code_frozen)")
    parser.add_argument("--rhoai-version", required=True)
    parser.add_argument("--effective-until", required=True)
    parser.add_argument(
        "--rhoaieng-url", default=None, help="RHOAIENG approval ticket URL (for PSX/OCPEXCEPT)"
    )
    parser.add_argument(
        "--remediation-plan-url", default=None,
        help="RHOAIENG resolution plan ticket URL (referenced in justification text)",
    )
    parser.add_argument("--psx-url", default=None, help="PSX ticket URL (for RHOAIENG back-ref)")
    parser.add_argument(
        "--link-to",
        default=None,
        help="Ticket key to link as Related (e.g. tracking Epic/Feature)",
    )
    parser.add_argument(
        "--summary-context",
        default=None,
        help="Brief context appended to ticket title",
    )
    parser.add_argument(
        "--vendor-tag",
        default=None,
        help="Vendor/distinguisher tag prepended to title, e.g. AMD, NVIDIA, FIPS",
    )
    parser.add_argument("--exception-scope", default=None, help="Exception scope (overrides template)")
    parser.add_argument("--exception-risk", default=None, help="Exception risk acceptance (overrides template)")
    parser.add_argument("--exception-remediation", default=None, help="Exception remediation plan (overrides template)")
    parser.add_argument("--exception-impact", default=None, help="Exception impact if denied (overrides template)")
    parser.add_argument(
        "--template",
        default=None,
        help="Template category ID from exception_templates.yaml (e.g., rpm_signature_thirdparty)",
    )
    parser.add_argument(
        "--authorized-party",
        default=None,
        help="Senior manager accepting risk (Authorized Party in PSX workflow)",
    )
    parser.add_argument(
        "--watchers",
        default=None,
        help=(
            "Comma-separated display names to add as watchers on the PSX ticket. "
            "These should come from the user-approved list suggested by "
            "preflight_check.py's discover_user_groups(). "
            "Example: --watchers 'Alex Fan,Chris Kodama,Jakub Stetina'"
        ),
    )
    parser.add_argument(
        "--purpose",
        default="approval",
        choices=["approval", "remediation"],
        help="RHOAIENG ticket purpose: approval (Blocker Bug) or remediation (Bug for fix)",
    )
    parser.add_argument(
        "--assignee",
        default=None,
        help="Jira display name to assign the ticket to",
    )
    parser.add_argument(
        "--reconcile",
        default=None,
        metavar="TICKET_KEY",
        help="Reconcile an existing ticket to expected state instead of creating new",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    components = [c.strip() for c in args.components.split(",")]

    # --- Resolve template + justification if provided ---
    if args.template:
        versions_str = args.rhoai_version or ""
        versions_list = [v.strip() for v in versions_str.split(",") if v.strip()]
        rule_key = args.rule.split(":", 1)[1] if ":" in args.rule else args.rule
        template_vars = {
            "rule": args.rule,
            "rule_key": rule_key,
            "components": ", ".join(components),
            "component_count": str(len(components)),
            "versions": ", ".join(versions_list) if versions_list else versions_str,
            "version_count": str(len(versions_list)) if versions_list else "1",
            "vendor": args.vendor_tag or "",
            "rhoaieng_exception_approval_url": args.rhoaieng_url or "",
            "remediation_plan_url": args.remediation_plan_url or "",
            "psx_url": args.psx_url or "",
            "effective_until": args.effective_until or "",
        }
        resolved = resolve_template(
            args.template, template_vars,
            justification_id=args.justification,
        )
        if not args.summary_context:
            args.summary_context = resolved.get("summary_context")
        if not args.exception_scope:
            args.exception_scope = resolved.get("scope")
        if not args.exception_risk:
            args.exception_risk = resolved.get("risk")
        if not args.exception_remediation:
            args.exception_remediation = resolved.get("remediation")
        if not args.exception_impact:
            args.exception_impact = resolved.get("impact")

    if args.reconcile:
        result = reconcile_ticket(
            ticket_key=args.reconcile,
            project=args.project,
            rule=args.rule,
            components=components,
            rhoai_version=args.rhoai_version,
            effective_until=args.effective_until,
            rhoaieng_url=args.rhoaieng_url,
            psx_url=args.psx_url,
            link_to=args.link_to,
            summary_context=args.summary_context,
            vendor_tag=args.vendor_tag,
            exception_scope=args.exception_scope,
            exception_risk=args.exception_risk,
            exception_remediation=args.exception_remediation,
            exception_impact=args.exception_impact,
            authorized_party=args.authorized_party,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "reconciled" else 1

    watcher_names: list[str] | None = None
    if args.watchers:
        watcher_names = [n.strip() for n in args.watchers.split(",") if n.strip()]

    result = create_ticket(
        project=args.project,
        rule=args.rule,
        components=components,
        rhoai_version=args.rhoai_version,
        effective_until=args.effective_until,
        rhoaieng_url=args.rhoaieng_url,
        psx_url=args.psx_url,
        link_to=args.link_to,
        summary_context=args.summary_context,
        vendor_tag=args.vendor_tag,
        exception_scope=args.exception_scope,
        exception_risk=args.exception_risk,
        exception_remediation=args.exception_remediation,
        exception_impact=args.exception_impact,
        authorized_party=args.authorized_party,
        watcher_names=watcher_names,
        purpose=args.purpose,
        assignee=args.assignee,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))
    if result.get("verification") and not result["verification"]["verified"]:
        print(
            "\nWARNING: Verification failed. Unmet expectations:",
            file=sys.stderr,
        )
        for item in result["verification"]["unmet"]:
            print(f"  - {item}", file=sys.stderr)
        return 1
    return 0 if result["status"] in ("created", "dry_run") else 1


if __name__ == "__main__":
    sys.exit(main())
