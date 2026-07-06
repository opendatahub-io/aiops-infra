"""Jira ticket description builders — ADF and text generation for all ticket types."""

from __future__ import annotations

from __future__ import annotations
import argparse
import getpass
import json
import os
import platform
import re
import sys
from pathlib import Path
import jira_ops
from add_jira_watchers import add_watchers_to_tickets as _add_jira_watchers


PROVENANCE_REPO = "opendatahub-io/aiops-infra"


def _ensure_jira_env() -> None:
    """Ensure jira env vars are available (konflux_environment.load() already handles this)."""
    pass


def _jira_auth() -> tuple[str, str] | None:
    """Return (email, base64-encoded auth header value) or None if not configured."""
    import base64

    token = os.environ.get("JIRA_API_TOKEN", "")
    email = os.environ.get("JIRA_EMAIL", "")
    if not token or not email:
        return None
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    return email, auth


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
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PUT",
    )
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


def build_provenance_footer() -> str:
    """Standard provenance footer for all tickets and comments."""
    return (
        "---\n"
        f"Created by 'conforma-exception' skill from {PROVENANCE_REPO}\n"
        f"User: {getpass.getuser()}@{platform.node()}"
    )


def build_exception_label(rule: str, components: list[str]) -> str:
    """Build the exception label: Exception - <rule>:<first-component>."""
    component_ref = components[0] if components else "unknown"
    return f"Exception - {rule}:{component_ref}"


def build_rhoaieng_description(
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


def build_rhoaieng_remediation_description(
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


def build_rhoaieng_violation_report_description(
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    fix_target_version: str | None = None,
    exception_scope: str | None = None,
) -> dict:
    """Build ADF description for RHOAIENG violation report ticket."""
    context_text = (
        f"Conforma Violation Report\n\n"
        f"Rule: {rule}\n"
        f"Components: {', '.join(components)}\n"
        f"RHOAI Version: {rhoai_version}\n"
        f"Effective Until: {effective_until}\n"
    )
    if fix_target_version:
        context_text += f"Fix Target Version: {fix_target_version}\n"
    if exception_scope:
        context_text += f"\nScope: {exception_scope}\n"

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


def build_psx_description(
    rule: str,
    components: list[str],
    rhoai_version: str,
    effective_until: str,
    rhoaieng_url: str,
) -> dict:
    """Build minimal ADF description for PSX/OCPEXCEPT ticket creation.

    This is used at creation time. The server may apply its own template,
    so fill_psx_template() is called after creation to fill in the real content.
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


def build_psx_filled_adf(
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
        "The affected RHOAI versions have already been released or are in "
        "code-freeze, therefore the violation cannot be fixed retroactively."
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
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
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
        f"Scope: {scope}\n\n"
        f"RHOAIENG tracking ticket: {rhoaieng_url}"
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
        _panel("Risk if we approve the exception?\nWhat risk is being accepted by approving this exception?"),
        _para(risk),
        _spacer(),
        _panel(
            "Impact of NOT approving the exception?\n"
            "Provide details on the impact that not approving this exception will have."
        ),
        _para(impact),
        _spacer(),
        _panel("Proposed remediation\nProvide a detailed description of the proposed plan to complete this work."),
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
        import urllib.parse
        import urllib.request

        creds = _jira_auth()
        if not creds:
            return {
                "ok": False,
                "action": "set_authorized_party",
                "error": "JIRA auth not configured",
            }
        _, auth = creds

        search_url = (
            f"https://redhat.atlassian.net/rest/api/3/user/search"
            f"?query={urllib.parse.quote(authorized_party)}&maxResults=5"
        )
        req = urllib.request.Request(
            search_url,
            headers={
                "Authorization": f"Basic {auth}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                users = json.loads(resp.read())
        except Exception as e:
            return {
                "ok": False,
                "action": "set_authorized_party",
                "error": f"user search failed: {e}",
            }

        for user in users:
            if user.get("displayName", "").lower() == authorized_party.lower():
                account_id = user["accountId"]
                matched_name = user.get("displayName", "")
                break

    if not account_id:
        return {
            "ok": False,
            "action": "set_authorized_party",
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


def fill_psx_template(
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

    adf = build_psx_filled_adf(
        rule,
        components,
        rhoai_version,
        effective_until,
        rhoaieng_url,
        exception_scope=exception_scope,
        exception_risk=exception_risk,
        exception_remediation=exception_remediation,
        exception_impact=exception_impact,
    )

    desc_result = _jira_rest_put(f"issue/{ticket_key}", {"fields": {"description": adf}})

    return {
        "action": "fill_psx_template",
        "ok": desc_result["ok"],
        "ticket_key": ticket_key,
        "description_status": desc_result.get("status", 0),
        "description_error": desc_result.get("error", ""),
        "authorized_party_set": ap_set,
    }


def build_summary(
    project: str,
    rule: str,
    components: list[str],
    rhoai_version: str,
    summary_context: str | None,
    vendor_tag: str | None,
    purpose: str = "approval",
) -> str:
    """Build the expected summary string for a ticket."""
    tag_prefix = f"[{vendor_tag}] " if vendor_tag else ""
    purpose_tags = {
        "violation_report": "[Conforma Violation] ",
        "remediation": "[Code Fix] ",
        "approval": "[Exception Approval] ",
    }
    purpose_tag = purpose_tags.get(purpose, "[Exception Approval] ")
    comp_str = ", ".join(components[:3])
    if len(components) > 3:
        comp_str += f" (+{len(components) - 3} more)"
    if summary_context:
        return f"{tag_prefix}{purpose_tag}{rule} - {comp_str} - {rhoai_version} - {summary_context}"
    return f"{tag_prefix}{purpose_tag}{rule} - {comp_str} - {rhoai_version}"

