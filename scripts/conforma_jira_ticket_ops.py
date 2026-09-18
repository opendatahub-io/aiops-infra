"""conforma_jira_ticket_ops.py -- Create and update Jira tickets for Conforma violations.

Discovers conforma-related Jira tickets label-first (all statuses, 7 projects),
self-heals the conforma label index, matches violations to tickets, and creates
conforma-violation tickets (project RHOAIENG, type Task, TargetVersion set,
priority Blocker) for violations that have no open ticket. Every Jira write is
set-then-verified and recorded in jira_sync.json.

Subcommands:
  create-jiras-for-conforma-violations
               Workflow mode: discover -> self-heal -> match -> group -> create/extend -> link -> write jira_sync.json
  find         Discovery only (read-only), prints the ticket table
  label-conforma-tickets
               Independently plan or apply Conforma labels to discovered tickets
  audit        Read-only validation of the conforma label index (self-healing labels applied)
  repair       audit + fill deterministically fillable fields
  prefill-url  Print the pre-filled Jira CreateIssueDetails URL for one rule + component group

Reuses: jira_ops (create/update/link/comment/search), conforma_constants (discovery scope),
conforma_context_ops (context auto-discovery), conforma_jira_ops (rule/component/version helpers),
component_catalog_ops (konflux -> jira component mapping).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import component_catalog_ops  # noqa: E402
import conforma_constants  # noqa: E402
import conforma_context_ops  # noqa: E402
import conforma_jira_ops  # noqa: E402
import conforma_mr_ops  # noqa: E402
import jira_ops  # noqa: E402

# ---------------------------------------------------------------------------
# Ticket-creation constants (single create target; discovery scope from constants)
# ---------------------------------------------------------------------------
CREATE_PROJECT = "RHOAIENG"
CREATE_PROJECT_ID = "10350"  # numeric project id for pre-filled CreateIssueDetails URLs (RHOAIENG)
CREATE_ISSUE_TYPE = "Task"
# CreateIssueDetails expects the numeric Jira issue-type id, not its display
# name.  Task is 10001 in the RHOAIENG Jira project.
CREATE_ISSUE_TYPE_ID = "10001"
TARGET_VERSION_FIELD = "customfield_10855"  # Jira "Target Version" (array), verified live
CREATE_PRIORITY = "Blocker"
TICKET_LABELS = [conforma_constants.CONFORMA_LABEL, conforma_constants.VIOLATION_LABEL]
LEGACY_EXCEPTION_LABEL = conforma_constants.LEGACY_EXCEPTION_LABEL
CONFORMA_LABEL = conforma_constants.CONFORMA_LABEL
VIOLATION_LABEL = conforma_constants.VIOLATION_LABEL

# Terminal/closed status names (case-insensitive). Anything else counts as open.
CLOSED_STATUS_NAMES = conforma_constants.CLOSED_STATUS_NAMES


# ---------------------------------------------------------------------------
# Pure helpers (no Jira) -- all unit-tested
# ---------------------------------------------------------------------------
def is_open(status: str | None) -> bool:
    """True if a Jira status name is not a terminal/closed state.

    Unknown/empty status is treated as open (do not silently drop a ticket).
    """
    return conforma_constants.is_open_jira_status(status)


def build_ticket_summary(rule: str, konflux_components: list[str]) -> str:
    """Deterministic ticket summary: 'Conforma violation: <rule> in <konflux components>'."""
    comps = ", ".join(konflux_components)
    return f"Conforma violation: {rule} in {comps}"


def _label_part(value: str) -> str:
    """Convert a value into a stable Jira-label-safe token."""
    token = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return token or "unknown"


def build_violation_label(release: str, component: str, rule: str) -> str:
    """Return the unique label for one release/component/violation tuple."""
    return "conforma-" + "-".join(
        [_label_part(release), _label_part(strip_version_suffix(component)), _label_part(rule)]
    )


def build_related_search_url(label: str) -> str:
    """Build a Jira search URL for a unique Conforma violation label."""
    jql = f'project = {CREATE_PROJECT} AND labels = "{label}" ORDER BY updated DESC'
    return f"{_JIRA_BASE}/issues/?jql={quote(jql, safe='')}"


def strip_version_suffix(name: str) -> str:
    """Strip a Konflux version suffix (reuses conforma_jira_ops helper)."""
    return conforma_jira_ops._strip_version_suffix(name)


def _component_text_components(konflux_components: list[str]) -> list[str]:
    """Version-stripped konflux component stems for text matching."""
    return [strip_version_suffix(c) for c in konflux_components]


def components_overlap(ticket: dict, konflux_components: list[str], jira_components: list[str]) -> bool:
    """Deterministic component signal between a ticket and a violation.

    True if any of:
      (a) a ticket component stem appears in a (version-stripped) konflux component,
      (b) a (version-stripped) konflux component appears in the ticket summary text,
      (c) a ticket Jira component is in the violation's mapped Jira components.
    """
    ticket_stems = conforma_jira_ops._extract_component_stems(ticket.get("summary", ""), ticket.get("description"))
    stripped_konflux = [s for s in _component_text_components(konflux_components)]
    summary_lower = (ticket.get("summary", "") or "").lower()

    for stem in ticket_stems:
        stem_l = stem.lower()
        if not stem_l:
            continue
        for kc in stripped_konflux:
            kc_l = kc.lower()
            if kc_l and (stem_l in kc_l or kc_l in stem_l):
                return True
    for kc in stripped_konflux:
        kc_l = kc.lower()
        if kc_l and kc_l in summary_lower:
            return True
    ticket_jira = [c.lower() for c in (ticket.get("components") or [])]
    for jc in jira_components or []:
        if jc and jc.lower() in ticket_jira:
            return True
    return False


def rule_matches(ticket: dict, rule: str) -> bool:
    """True if the ticket's summary/description is about *rule* (reuses conforma_jira_ops)."""
    extracted = conforma_jira_ops._extract_rule_from_summary(ticket.get("summary", "") or "")
    if extracted == rule:
        return True
    text = (ticket.get("summary", "") or "") + " " + (ticket.get("description", "") or "")
    return conforma_jira_ops._infer_rule_from_text(text, rule) == "confirmed"


def match_violation_to_tickets(violation: dict, tickets: list[dict]) -> dict:
    """Match a violation to discovered tickets.

    Returns {"existing": ticket|None, "prior_issues": [ticket, ...]}.
    A match requires a rule match AND >=1 component signal. Open match -> existing;
    closed match -> prior issue.
    """
    konflux = violation.get("uncovered_components") or violation.get("all_components") or []
    jira_comps = violation.get("jira_components") or []
    existing = None
    prior_issues: list[dict] = []
    for ticket in tickets:
        if not rule_matches(ticket, violation["rule"]):
            continue
        if not components_overlap(ticket, konflux, jira_comps):
            continue
        if is_open(ticket.get("status")):
            if existing is None:
                existing = ticket
        else:
            prior_issues.append(ticket)
    return {"existing": existing, "prior_issues": prior_issues}


def group_components_by_jira(konflux_components: list[str], catalog: list[dict]) -> list[dict]:
    """Group konflux components by their resolved Jira component (catalog mapping).

    Components that do not resolve map to an "Unmapped" group (reported, not dropped).
    Returns a list of {"jira_component": str|None, "team": str|None, "konflux_components": [..]}.
    """
    mapping = component_catalog_ops.resolve_jira_components(konflux_components, catalog)
    groups: dict[str | None, list[str]] = {}
    for kc in konflux_components:
        jc = mapping.get(kc)
        groups.setdefault(jc, []).append(kc)
    result = []
    for jc, members in groups.items():
        result.append(
            {
                "jira_component": jc,
                "team": _team_for_component(jc, catalog),
                "konflux_components": members,
            }
        )
    return result


def _team_for_component(jira_component: str | None, catalog: list[dict]) -> str | None:
    """Best-effort team/org for a Jira component from catalog entries (None if unknown)."""
    if not jira_component:
        return None
    target = jira_component.lower()
    for entry in catalog:
        for jc in entry.get("jira_components", []) or []:
            jc_name = jc.get("name") if isinstance(jc, dict) else jc
            if jc_name and jc_name.lower() == target:
                return entry.get("team") or entry.get("org") or None
    return None


def resolve_target_version(release: str) -> str | None:
    """Deterministically resolve the Jira TargetVersion value from the analyzed release.

    The tenant's TargetVersion is an array field whose allowed values are not exposed
    by createmeta. We use the normalized analyzed release as the value; if the release
    is empty/blank we return None (field left unset, reported as 'unmapped' — never guessed).
    """
    if not release:
        return None
    normalized = conforma_jira_ops._normalize_version(release)
    return normalized or None


def build_ticket_description(
    rule: str,
    release: str,
    environment: str,
    konflux_components: list[str],
    jira_component: str | None,
    team: str | None,
    violation_details: str,
    source_csv_url: str,
    prior_issues: list[dict],
) -> str:
    """Deterministic ticket description (plain text)."""
    lines = [
        f"Conforma violation: {rule}",
        "",
        f"Release: {release}",
        f"Environment: {environment}",
        f"Konflux components: {', '.join(konflux_components)}",
    ]
    if jira_component:
        lines.append(f"Jira component: {jira_component}")
    if team:
        lines.append(f"Owning team/org: {team}")
    lines.append("")
    lines.append("Violation details:")
    lines.append(violation_details)
    if source_csv_url:
        lines.append("")
        lines.append(f"Source report: {source_csv_url}")
    if prior_issues:
        lines.append("")
        lines.append("Relates to prior issue:")
        for p in prior_issues:
            lines.append(f"  - {p.get('key')} ({p.get('status')})")
    return "\n".join(lines)


def build_create_fields(
    rule: str,
    konflux_components: list[str],
    jira_components: list[str],
    target_version: str | None,
    description: str,
    release: str = "",
) -> dict:
    """Pure builder for the create-issue payload (shared source of truth for the
    actually-created ticket and the pre-filled URL).

    Uses TargetVersion (customfield_10855), NOT fixVersion.
    """
    fields: dict = {
        "project": {"key": CREATE_PROJECT},
        "summary": build_ticket_summary(rule, konflux_components),
        "issuetype": {"name": CREATE_ISSUE_TYPE},
        "labels": list(TICKET_LABELS)
        + (
            [build_violation_label(release, component, rule) for component in konflux_components]
            if release
            else []
        ),
        "priority": {"name": CREATE_PRIORITY},
        "description": description,
    }
    if jira_components:
        fields["components"] = [{"name": c} for c in jira_components]
    if target_version:
        fields[TARGET_VERSION_FIELD] = [{"name": target_version}]
    return fields


def build_prefill_url(
    project_id: str,
    rule: str,
    konflux_components: list[str],
    jira_components: list[str],
    target_version: str | None,
    description: str,
    release: str = "",
) -> str:
    """Pure builder for the Jira CreateIssueDetails pre-filled URL.

    All params URL-encoded. `issuetype`/`priority`/`labels`/`components` use Jira's
    CreateIssueDetails param conventions (comma/space-separated display names; labels
    comma-separated).
    """
    params = {
        "pid": project_id,
        "issuetype": CREATE_ISSUE_TYPE_ID,
        "summary": build_ticket_summary(rule, konflux_components),
        "labels": ",".join(
            list(TICKET_LABELS)
            + (
                [build_violation_label(release, component, rule) for component in konflux_components]
                if release
                else []
            )
        ),
        "priority": CREATE_PRIORITY,
        "description": description,
    }
    if jira_components:
        params["components"] = ",".join(jira_components)
    if target_version:
        params[TARGET_VERSION_FIELD] = target_version
    return f"{_JIRA_BASE}/secure/CreateIssueDetails!init.jspa?{urlencode(params)}"


def _jira_base() -> str:
    import os

    return os.environ.get("JIRA_URL", jira_ops.DEFAULT_JIRA_URL).rstrip("/")


_JIRA_BASE = _jira_base()


def plan_self_heal_labels(tickets: list[dict]) -> list[dict]:
    """Pure plan: which labels each ticket needs added (no Jira calls).

    Rules:
      - every ticket lacking 'conforma' gets 'conforma'
      - a violation ticket (summary starts with 'Conforma violation:' or a rule is
        extractable) ALSO gets 'conforma-violation'
      - a legacy exception ticket (has 'conforma-exception-ai-skill') gets 'conforma'
        only, NEVER 'conforma-violation'
    Returns [{"key":..., "add": [..], "current": [..]}] for tickets needing changes.
    """
    plan = []
    for ticket in tickets:
        current = list(ticket.get("labels") or [])
        add: list[str] = []
        if CONFORMA_LABEL not in current:
            add.append(CONFORMA_LABEL)
        is_legacy_exception = LEGACY_EXCEPTION_LABEL in current
        is_violation = (ticket.get("summary", "") or "").startswith("Conforma violation:")
        if not is_legacy_exception and is_violation and VIOLATION_LABEL not in current:
            add.append(VIOLATION_LABEL)
        if add:
            plan.append({"key": ticket.get("key"), "add": add, "current": current})
    return plan


# ---------------------------------------------------------------------------
# I/O operations (Jira) -- unit-tested with mocks
# ---------------------------------------------------------------------------
def discover_conforma_tickets(
    projects: list[str] | None = None,
    labels: list[str] | None = None,
    violations: list[dict] | None = None,
    release: str = "",
) -> list[dict]:
    """Discover Conforma tickets across all statuses.

    The generic label query remains the baseline.  When violation context is
    available, add exact unique-label and rule/component text candidates so a
    manually created ticket can be found before it has been self-healed.
    """
    project_names = projects or conforma_constants.CONFORMA_DISCOVERY_PROJECTS
    base_jql = conforma_constants.build_label_discovery_jql(
        projects=project_names,
        labels=labels or conforma_constants.CONFORMA_DISCOVERY_LABELS,
    )
    related_clauses: list[str] = []
    for violation in violations or []:
        rule = violation.get("rule") or ""
        rule_text = rule.split(":", 1)[0]
        components = violation.get("uncovered_components") or violation.get("all_components") or []
        for component in components:
            unique_label = build_violation_label(release, component, rule) if release else ""
            label_clause = f'labels = "{unique_label}" OR ' if unique_label else ""
            stem = strip_version_suffix(component)
            if rule_text and stem:
                related_clauses.append(
                    f'({label_clause}(summary ~ "{rule_text}" AND (summary ~ "{stem}" OR description ~ "{stem}")))'
                )
    if related_clauses:
        project_clause = f"project in ({', '.join(project_names)})"
        jql = f"{project_clause} AND ({base_jql.split(' AND ', 1)[1]} OR {' OR '.join(related_clauses)})"
    else:
        jql = base_jql
    result = jira_ops.search_issues(
        jql,
        max_results=500,
        # Every field here must be a field search_issues() extracts (see its
        # docstring): audit/_ticket_ref need
        # assignee/fix_versions/target_versions, so request those instead.
        fields=[
            "key",
            "summary",
            "status",
            "issuetype",
            "labels",
            "components",
            "priority",
            "assignee",
            "fixVersions",
            "target_versions",
            "description",
        ],
    )
    tickets = result.get("issues", [])
    if not violations:
        return tickets

    # Merge Request descriptions and commit messages are a second, independent
    # discovery source.  GitLab failures intentionally propagate from this
    # call; returning Jira-only results would make the report incomplete.
    mr_references = conforma_mr_ops.discover_jira_references()
    references_by_key: dict[str, list[dict]] = {}
    for reference in mr_references:
        references_by_key.setdefault(reference["key"], []).append(reference)
    missing_keys = [key for key in references_by_key if not any(t.get("key") == key for t in tickets)]
    if missing_keys:
        referenced = jira_ops.search_issues(
            f"key in ({', '.join(missing_keys)})",
            max_results=len(missing_keys),
            fields=[
                "key",
                "summary",
                "status",
                "issuetype",
                "labels",
                "components",
                "priority",
                "assignee",
                "fixVersions",
                "target_versions",
                "description",
            ],
        )
        tickets.extend(referenced.get("issues", []))
    for ticket in tickets:
        if ticket.get("key") in references_by_key:
            ticket["merge_request_references"] = references_by_key[ticket["key"]]
    return tickets


def self_heal_labels(tickets: list[dict]) -> list[str]:
    """Apply the pure self-heal plan (set-then-verified). Returns an action log."""
    actions: list[str] = []
    for item in plan_self_heal_labels(tickets):
        ticket = next((t for t in tickets if t.get("key") == item["key"]), None)
        if ticket is None:
            continue
        new_labels = item["current"] + item["add"]
        updated = jira_ops.update_issue(item["key"], labels=new_labels)
        if "error" in updated:
            actions.append(f"label-failed {item['key']} (add {','.join(item['add'])}): {updated['error']}")
            continue
        # set-then-verify
        verified = jira_ops.get_issue(item["key"], fields=["labels"])
        got_labels = set(verified.get("labels") or [])
        if all(lbl in got_labels for lbl in item["add"]):
            actions.append(f"labeled {item['key']} +{'+'.join(item['add'])}")
        else:
            actions.append(f"label-verify-failed {item['key']} (expected {item['add']}, got {sorted(got_labels)})")
    return actions


def label_conforma_tickets(apply: bool = False) -> dict:
    """Plan or apply labels independently of Jira ticket creation and sync.

    Discovery uses the current violation context when available, but never
    reads ``jira_sync.json`` or depends on a ticket-creation result.  The
    default is read-only; callers must explicitly pass ``apply=True`` before
    Jira labels are changed.
    """
    run_dir, context = _load_context()
    release = _release_from_context(context)
    violations_path = run_dir / "coverage.json"
    violations: list[dict] = []
    if violations_path.is_file():
        violations = _load_coverage_violations(run_dir)

    tickets = discover_conforma_tickets(violations=violations or None, release=release)
    plan = plan_self_heal_labels(tickets)
    actions: list[dict] = []
    if apply:
        for item in plan:
            ticket = next((t for t in tickets if t.get("key") == item["key"]), None)
            if ticket is None:
                actions.append({"key": item["key"], "status": "skipped", "reason": "ticket not in discovery result"})
                continue
            updated = jira_ops.update_issue(item["key"], labels=item["current"] + item["add"])
            if "error" in updated:
                actions.append({"key": item["key"], "status": "failed", "error": updated["error"]})
                continue
            verified = jira_ops.get_issue(item["key"], fields=["labels"])
            got_labels = set(verified.get("labels") or [])
            if all(label in got_labels for label in item["add"]):
                actions.append({"key": item["key"], "status": "labeled", "added": item["add"]})
            else:
                actions.append(
                    {
                        "key": item["key"],
                        "status": "verification_failed",
                        "expected": item["add"],
                        "actual": sorted(got_labels),
                    }
                )
    else:
        actions = [{"key": item["key"], "status": "planned", "add": item["add"]} for item in plan]

    status = "completed" if apply else "pending_confirmation"
    output = {
        "discovered": len(tickets),
        "planned": len(plan),
        "actions": actions,
        "apply": apply,
        "release": release,
    }
    if not apply:
        output["display"] = (
            f"Discovered {len(tickets)} Conforma-related Jira tickets. "
            f"Proposed label updates: {len(plan)}."
        )
        output["user_question"] = {
            "question_text": f"Apply the {len(plan)} proposed Conforma Jira label update(s)?",
            "question_options": ["Yes, apply labels", "No, skip labelling"],
        }
    report_path = run_dir / "jira_labelling.json"
    report_path.write_text(json.dumps(output, indent=2))
    conforma_context_ops.update_step(
        run_dir,
        "jira_labelling",
        status,
        jira_labelling_json="jira_labelling.json",
        discovered=len(tickets),
        planned=len(plan),
        applied=sum(action.get("status") == "labeled" for action in actions),
    )
    return output


def create_violation_ticket(
    rule: str,
    konflux_components: list[str],
    jira_components: list[str],
    target_version: str | None,
    description: str,
    release: str = "",
) -> dict:
    """Create the conforma-violation ticket (TargetVersion, Blocker). Set-then-verify."""
    fields = build_create_fields(rule, konflux_components, jira_components, target_version, description, release)
    labels = fields["labels"]
    result = jira_ops.create_issue(
        project=CREATE_PROJECT,
        summary=fields["summary"],
        description=fields["description"],
        issue_type=CREATE_ISSUE_TYPE,
        components=jira_components or None,
        labels=labels,
        priority=CREATE_PRIORITY,
        extra_fields={TARGET_VERSION_FIELD: fields[TARGET_VERSION_FIELD]} if target_version else None,
    )
    if "error" in result:
        return {"created": None, "error": result["error"], "fields": fields}
    key = result["key"]
    # set-then-verify
    verified = jira_ops.get_issue(key, fields=["labels", "priority", "components"])
    verify: dict = {
        "key": key,
        "url": result["url"],
        "labels_ok": set(labels).issubset(set(verified.get("labels") or [])),
        "priority_ok": (verified.get("priority") or "") == CREATE_PRIORITY,
        "components": verified.get("components") or [],
    }
    return {"created": verify, "fields": fields}


def extend_partial_match(ticket_key: str, missing_components: list[str]) -> dict:
    """Add missing Jira components to an existing open ticket (set-then-verify) + comment."""
    if not missing_components:
        return {"extended": None, "reason": "no missing components"}
    current = jira_ops.get_issue(ticket_key, fields=["components"])
    existing = list(current.get("components") or [])
    union = existing + [c for c in missing_components if c not in existing]
    updated = jira_ops.update_issue(ticket_key, components=union)
    if "error" in updated:
        return {"extended": None, "error": updated["error"]}
    jira_ops.add_comment(
        ticket_key,
        f"Conforma sync: added Jira component(s) {', '.join(missing_components)} for this violation.",
    )
    return {"extended": {"key": ticket_key, "components_added": missing_components}}


def link_ticket(from_key: str, to_key: str, link_type: str = "Relates") -> bool:
    """Link two tickets; returns True on success, False on error."""
    result = jira_ops.link_issues(from_key, to_key, link_type=link_type)
    return "error" not in result


def add_guide_url_comment(created_keys: list[str], guide_url: str) -> list[str]:
    """Non-blocking: comment the guide URL on each created ticket. Never raises."""
    actions: list[str] = []
    for key in created_keys:
        try:
            result = jira_ops.add_comment(key, f"Resolution guide: {guide_url}")
            if "error" in result:
                actions.append(f"guide-comment-failed {key}: {result['error']}")
            else:
                actions.append(f"guide-commented {key}")
        except Exception as exc:  # noqa: BLE001 -- non-blocking by design
            actions.append(f"guide-comment-failed {key}: {exc}")
    return actions


def audit_conforma_index(tickets: list[dict], release: str) -> dict:
    """Read-only tiered audit of the conforma label index (excluding closed-exempt checks).

    Returns {"checked": int, "gaps": [ {key, missing: [..], notes: [..]} ]}.
    """
    gaps: list[dict] = []
    for ticket in tickets:
        missing: list[str] = []
        notes: list[str] = []
        labels = set(ticket.get("labels") or [])
        if CONFORMA_LABEL not in labels:
            missing.append("conforma")
        is_violation = (ticket.get("summary", "") or "").startswith("Conforma violation:")
        if is_violation and VIOLATION_LABEL not in labels and LEGACY_EXCEPTION_LABEL not in labels:
            missing.append("conforma-violation")
        if not (ticket.get("components") or []):
            missing.append("components")
        if (ticket.get("priority") or "") != CREATE_PRIORITY:
            missing.append("priority")
        if not (ticket.get("target_versions") or []):
            missing.append("target_versions")
        if not (ticket.get("assignee") or "") and ticket.get("assignee") is not None:
            notes.append("unassigned -- route to owning team")
        if not is_open(ticket.get("status")):
            notes.append(f"closed ({ticket.get('status')}); exempt from fills")
        if missing or notes:
            gaps.append({"key": ticket.get("key"), "missing": missing, "notes": notes})
    return {"checked": len(tickets), "gaps": gaps}


def repair_index(tickets: list[dict], release: str, catalog: list[dict]) -> list[str]:
    """Fill deterministically fillable gaps (labels self-heal, priority, components, target version).

    Never guesses an assignee (no lead data). Closed tickets are exempt from the
    target-version fill. Returns an action log.
    """
    actions: list[str] = self_heal_labels(tickets)
    target_version = resolve_target_version(release)
    for ticket in tickets:
        key = ticket.get("key")
        if not key:
            continue
        fields: dict = {}
        if (ticket.get("priority") or "") != CREATE_PRIORITY:
            fields["priority"] = CREATE_PRIORITY
        if not (ticket.get("components") or []):
            stems = conforma_jira_ops._extract_component_stems(ticket.get("summary", ""), ticket.get("description"))
            resolved = [j for j in (component_catalog_ops.resolve_jira_components(stems, catalog).values() or []) if j]
            if resolved:
                fields["components"] = resolved
        if target_version and not (ticket.get("target_versions") or []) and is_open(ticket.get("status")):
            fields[TARGET_VERSION_FIELD] = [{"name": target_version}]
        if fields:
            extra = {k: v for k, v in fields.items() if k not in ("priority", "components")}
            updated = jira_ops.update_issue(
                key,
                priority=fields.get("priority"),
                components=fields.get("components"),
                extra_fields=extra or None,
            )
            if "error" in updated:
                actions.append(f"repair-failed {key}: {updated['error']}")
            else:
                actions.append(f"repaired {key}: {updated['updated']}")
    return actions


# ---------------------------------------------------------------------------
# Orchestrators + CLI
# ---------------------------------------------------------------------------
def _load_context():
    """Discover the active run dir + context.yaml. Hard stop if missing."""
    run_dir = conforma_context_ops.discover_run_dir()
    context = conforma_context_ops.load(run_dir)
    return run_dir, context


def _release_from_context(context: dict) -> str:
    application = context.get("application") or {}
    return application.get("release") or application.get("version") or context.get("user_query") or ""


def _load_coverage_violations(run_dir: Path) -> list[dict]:
    path = run_dir / "coverage.json"
    if not path.is_file():
        raise RuntimeError(f"coverage.json not found in run dir {run_dir}; run the coverage step first")
    data = json.loads(path.read_text())
    return data.get("violations", [])


def _load_catalog() -> list[dict]:
    """Load the software catalog; on failure return [] (groups fall back to Unmapped)."""
    try:
        return component_catalog_ops.load_catalog()
    except Exception:  # noqa: BLE001 -- catalog is best-effort for grouping
        return []


def prepare_violation_groups(
    violation: dict, tickets: list[dict], catalog: list[dict], release: str = ""
) -> dict:
    """Pure: match a violation to tickets and split its uncovered components into Jira groups.

    Only uncovered components are grouped (covered components already have exceptions), so
    the create/extend decision acts only on what is left to cover. Returns a
    jira_sync.json-shaped "violations" entry (without created/extended).
    """
    all_components = violation.get("all_components") or []
    uncovered = violation.get("uncovered_components") or all_components
    rule = violation["rule"]
    match = match_violation_to_tickets(violation, tickets)
    existing_ref = _ticket_ref(match["existing"]) if match["existing"] else None
    prior_refs = [_ticket_ref(p) for p in match["prior_issues"]]
    groups = []
    for group in group_components_by_jira(uncovered, catalog):
        jc = group["jira_component"]
        groups.append(
            {
                "jira_component": jc or "Unmapped",
                "team": group["team"],
                "konflux_components": group["konflux_components"],
                "existing": existing_ref,
                "prior_issues": prior_refs,
                "unique_labels": [
                    build_violation_label(release, component, rule)
                    for component in group["konflux_components"]
                ],
            }
        )
    return {
        "rule": rule,
        "coverage": violation.get("coverage") or "not_covered",
        "uncovered_components": uncovered,
        "groups": groups,
    }


def _ticket_ref(ticket: dict) -> dict:
    return {
        "key": ticket.get("key"),
        "status": ticket.get("status"),
        "url": ticket.get("url"),
        "components": list(ticket.get("components") or []),
        "release_relevance": conforma_jira_ops.classify_ticket_version_relevance(
            ticket, ticket.get("_analyzed_release", "")
        )
        if ticket.get("_analyzed_release")
        else "unknown",
    }


def sync(dry_run: bool = False) -> dict:
    """Full workflow sync: discover -> self-heal -> match -> group -> create/extend -> link.

    Writes jira_sync.json to the run dir and persists steps.jira_sync to context.yaml.
    dry_run=True: no Jira writes (discovery is read-only; create/extend/label recorded as planned).
    """
    run_dir, context = _load_context()
    release = _release_from_context(context)
    environment = context.get("environment", "prod")
    violations = _load_coverage_violations(run_dir)
    catalog = _load_catalog()

    # discovery
    tickets = discover_conforma_tickets(violations=violations, release=release)
    for t in tickets:
        t["_analyzed_release"] = release
    if dry_run:
        self_heal_actions: list[str] = [
            f"[dry-run] plan: {p['add']} -> {p['key']}" for p in plan_self_heal_labels(tickets)
        ]
    else:
        self_heal_actions = self_heal_labels(tickets)

    target_version = resolve_target_version(release)
    violations_out: list[dict] = []
    actions: list[str] = list(self_heal_actions)
    created_keys: list[str] = []
    link_plans: list[tuple[str, str]] = []

    for violation in violations:
        prepared = prepare_violation_groups(violation, tickets, catalog, release)
        # skip fully covered violations (no uncovered components)
        if not prepared["uncovered_components"]:
            continue
        groups = prepared["groups"]
        if not groups:
            violations_out.append(prepared)
            continue
        # All groups share the same match result; an existing open ticket, if any,
        # blocks creation and only triggers extension for genuinely-missing components.
        existing = groups[0].get("existing")
        prior_issues = groups[0].get("prior_issues") or []
        for group in groups:
            if group.get("unique_labels"):
                group["related_search_url"] = build_related_search_url(group["unique_labels"][0])
        mapped_components = _map_jira_components(groups)
        if existing and not dry_run:
            existing_key = existing.get("key")
            # Discovery already requests Jira components.  Reuse them and only
            # fetch the issue when an older discovery result omitted the field.
            current_components = existing.get("components") or _existing_component_names(existing_key)
            missing = [jc for jc in mapped_components if jc not in current_components]
            if missing:
                ext = extend_partial_match(existing_key, missing)
                if ext.get("extended"):
                    for group in groups:
                        group["extended"] = ext["extended"]
                    actions.append(f"extended {existing_key} +{', '.join(missing)}")
                elif ext.get("error"):
                    actions.append(f"extend-failed {existing_key}: {ext['error']}")
        else:
            for group in groups:
                if existing:
                    # dry_run with an existing open ticket: an open ticket already
                    # covers this violation, so creation is blocked -- do not emit
                    # a misleading create_url / created marker for the group.
                    continue
                jc = _jira_component_for_group(group)
                description = build_ticket_description(
                    rule=prepared["rule"],
                    release=release,
                    environment=environment,
                    konflux_components=group["konflux_components"],
                    jira_component=jc,
                    team=group["team"],
                    violation_details=violation.get("detail", ""),
                    source_csv_url=conforma_constants.build_report_url(release, environment),
                    prior_issues=prior_issues,
                )
                group["create_url"] = build_prefill_url(
                    CREATE_PROJECT_ID,
                    prepared["rule"],
                    group["konflux_components"],
                    [jc] if jc else [],
                    target_version,
                    description,
                    release,
                )
                group["unique_labels"] = [
                    build_violation_label(release, component, prepared["rule"])
                    for component in group["konflux_components"]
                ]
                group["related_search_url"] = build_related_search_url(group["unique_labels"][0])
                if dry_run:
                    group["created"] = {
                        "dry_run": True,
                        "summary": build_ticket_summary(prepared["rule"], group["konflux_components"]),
                    }
                    actions.append(
                        f"[dry-run] would create {build_ticket_summary(prepared['rule'], group['konflux_components'])}"
                    )
                else:
                    result = create_violation_ticket(
                        prepared["rule"],
                        group["konflux_components"],
                        [jc] if jc else [],
                        target_version,
                        description,
                        release,
                    )
                    if result.get("created"):
                        new_key = result["created"]["key"]
                        group["created"] = {
                            "key": new_key,
                            "url": result["created"]["url"],
                            "target_version": target_version,
                        }
                        created_keys.append(new_key)
                        actions.append(f"created {new_key} ({prepared['rule']} {group['jira_component']})")
                        for p in prior_issues:
                            if p.get("key"):
                                link_plans.append((new_key, p["key"]))
                    else:
                        group["create_error"] = result.get("error")
                        actions.append(f"create-failed {prepared['rule']}: {result.get('error')}")
        violations_out.append(prepared)

    if not dry_run:
        for a, b in link_plans:
            ok = link_ticket(a, b)
            actions.append(f"linked {a} -> {b} (relates)" if ok else f"link-failed {a} -> {b}")

    sync_output = {
        "release": release,
        "environment": environment,
        "generated_at": _now_iso(),
        "projects_searched": conforma_constants.CONFORMA_DISCOVERY_PROJECTS,
        "discovered": [_ticket_ref(t) for t in tickets],
        "violations": violations_out,
        "actions": actions,
        "dry_run": dry_run,
    }
    if not dry_run:
        out_path = run_dir / "jira_sync.json"
        out_path.write_text(json.dumps(sync_output, indent=2))
        conforma_context_ops.update_step(
            run_dir,
            "jira_sync",
            "completed",
            jira_sync_json="jira_sync.json",
            created=len(created_keys),
            actions=len(actions),
        )
    return sync_output


def _jira_component_for_group(group: dict) -> str | None:
    """The group's mapped Jira component name, or None if the group is unmapped."""
    jc = group.get("jira_component")
    return None if jc in (None, "Unmapped") else jc


def _map_jira_components(groups: list[dict]) -> list[str]:
    """Unique mapped Jira component names across groups, in first-appearance order."""
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        jc = _jira_component_for_group(group)
        if jc and jc not in seen:
            seen.add(jc)
            result.append(jc)
    return result


def _existing_component_names(ticket_key: str) -> list[str]:
    """Fetch a ticket's current Jira component names (empty list on any failure)."""
    detail = jira_ops.get_issue(ticket_key, fields=["components"])
    return list(detail.get("components") or [])


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compact_summary(sync_output: dict) -> str:
    """Compact chat summary of the sync run (over-communication encouraged)."""
    actions = sync_output.get("actions", [])
    created = [a for a in actions if a.startswith("created ")]
    extended = [a for a in actions if a.startswith("extended ")]
    labeled = [a for a in actions if a.startswith("labeled ")]
    linked = [a for a in actions if a.startswith("linked ")]
    prior = 0
    for violation in sync_output.get("violations", []):
        groups = violation.get("groups") or []
        if groups:
            prior += len(groups[0].get("prior_issues", []))
    lines = [
        "## Jira sync summary",
        f"- Discovered: {len(sync_output.get('discovered', []))} tickets",
        f"- Created: {len(created)}" + (f" ({', '.join(a.split()[1] for a in created)})" if created else ""),
        f"- Extended: {len(extended)}" + (f" ({', '.join(a.split()[1] for a in extended)})" if extended else ""),
        f"- Self-healed labels: {len(labeled)}" + (f" ({', '.join(a.split()[1] for a in labeled)})" if labeled else ""),
        f"- Linked: {len(linked)}",
        f"- Prior issues (closed, context only): {prior}",
    ]
    return "\n".join(lines)


def cmd_find() -> int:
    """Discovery only: print the ticket table. Always read-only —
    label self-healing is the job of the audit/repair/sync commands."""
    tickets = discover_conforma_tickets()
    print(f"Discovered {len(tickets)} conforma tickets:")
    for t in tickets:
        status = t.get("status", "?")
        role = "existing" if is_open(status) else "prior-issue"
        print(f"  {t.get('key')}  [{role}]  {status}  {t.get('summary', '')}")
    return 0


def cmd_label(apply: bool = False) -> int:
    """Plan or apply independent Conforma labels and print JSON output."""
    output = label_conforma_tickets(apply=apply)
    print(json.dumps(output, indent=2))
    return 0


def cmd_audit() -> int:
    """Audit the conforma index (self-heal labels applied)."""
    tickets = discover_conforma_tickets()
    actions = self_heal_labels(tickets)
    report = audit_conforma_index(tickets, "")
    for a in actions:
        print(f"  {a}")
    print(f"Audited {report['checked']} tickets; {len(report['gaps'])} with gaps:")
    for gap in report["gaps"]:
        print(f"  {gap['key']}: missing={gap['missing']} notes={gap['notes']}")
    return 0


def cmd_repair() -> int:
    """Audit + repair."""
    tickets = discover_conforma_tickets()
    catalog = _load_catalog()
    run_dir, context = _load_context()
    release = _release_from_context(context)
    actions = repair_index(tickets, release, catalog)
    for a in actions:
        print(f"  {a}")
    return 0


def cmd_prefill_url(rule: str, components_csv: str, project_id: str) -> int:
    """Print the pre-filled CreateIssueDetails URL for one rule + component group."""
    konflux = [c.strip() for c in components_csv.split(",") if c.strip()]
    catalog = _load_catalog()
    groups = group_components_by_jira(konflux, catalog)
    group = groups[0] if groups else {"jira_component": None, "team": None, "konflux_components": konflux}
    jc = group["jira_component"]
    _run_dir, context = _load_context()
    release = _release_from_context(context)
    environment = context.get("environment", "prod")
    description = build_ticket_description(
        rule=rule,
        release=release,
        environment=environment,
        konflux_components=group["konflux_components"],
        jira_component=jc,
        team=group["team"],
        violation_details="",
        source_csv_url=conforma_constants.build_report_url(release, environment),
        prior_issues=[],
    )
    url = build_prefill_url(
        project_id,
        rule,
        group["konflux_components"],
        [jc] if jc else [],
        resolve_target_version(release),
        description,
    )
    print(url)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create and update Jira tickets for Conforma violations (dual-mode)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sync_p = sub.add_parser(
        "create-jiras-for-conforma-violations",
        help="Create or update Jira tickets for the analyzed Conforma violations",
    )
    sync_p.add_argument("--dry-run", action="store_true", help="No Jira writes (discovery read-only, create planned)")

    sub.add_parser("find", help="Discovery only (read-only, no label self-heal)")

    label_p = sub.add_parser(
        "label-conforma-tickets",
        help="Plan or apply Conforma labels independently of Jira ticket sync",
    )
    label_p.add_argument("--apply", action="store_true", help="Apply the planned labels after explicit confirmation")

    sub.add_parser("audit", help="Audit the conforma index")
    sub.add_parser("repair", help="Audit + repair")

    prefill_p = sub.add_parser("prefill-url", help="Pre-filled create URL")
    prefill_p.add_argument("--rule", required=True)
    prefill_p.add_argument("--components", required=True, help="Comma-separated Konflux component names")
    prefill_p.add_argument("--project-id", default=CREATE_PROJECT_ID, help="RHOAIENG project id (default 10350)")

    args = parser.parse_args()
    try:
        if args.command == "create-jiras-for-conforma-violations":
            out = sync(dry_run=args.dry_run)
            print(json.dumps(out, indent=2))
            print(compact_summary(out))
        elif args.command == "find":
            return cmd_find()
        elif args.command == "label-conforma-tickets":
            return cmd_label(apply=args.apply)
        elif args.command == "audit":
            return cmd_audit()
        elif args.command == "repair":
            return cmd_repair()
        elif args.command == "prefill-url":
            return cmd_prefill_url(args.rule, args.components, args.project_id)
    except jira_ops.JiraSearchError as exc:
        print(json.dumps(exc.to_dict()), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
