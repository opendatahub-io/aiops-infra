---
name: conforma-remedy
description: Find and apply fixes to underlying conforma violations in component code, configs, or build pipelines.
allowed-tools: Bash(python3:*,gh:*,git:*)
user-invocable: true
---

# Conforma Remedy

Find and apply fixes to underlying conforma violations. This skill focuses on resolving violations in component code, configuration, or build pipelines — the preferred path before creating exceptions.

## Quick Start

This skill is part of the conforma suite in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

**Setup:** See [README.md](README.md) for installation and prerequisites.

## Violations-First Philosophy

This skill embodies the core principle: **fix the violation, don't just waive it.** Exceptions should only be created when a code fix is genuinely not feasible within the release timeline.

## Violation Catalog

All violation knowledge lives in the shared **violation catalog**:

```
skills/references/violation-catalog.yaml
```

This file is the single source of truth for:
- What each violation type means
- How to fix it (step-by-step)
- When to escalate to `conforma-exception` instead
- Known false alerts that can be ignored

## Workflow

When the user asks to fix/remedy/resolve/troubleshoot/diagnose a violation:

### 1. Identify the violation

Determine the violation type from the user's input. The user may provide:
- An exact conforma rule code (e.g., `hermetic_task.hermetic`)
- A natural-language phrase (e.g., "hermetic build", "untrusted task")
- A violation message from a conforma report
- A specific component name + violation combination

**Read** `skills/references/violation-catalog.yaml` and match the user's input against:
- The `conforma_rule_codes` field (exact match)
- The `aliases` field (phrase match)
- The `symptoms` field (message match)

If the violation code is NOT in the catalog, inform the user that this is an unrecognized violation type and suggest:
- Consulting the `conforma-docs` skill for documentation
- Asking on #konflux-users Slack for guidance

### 2. Check for known false alerts

Check the `known_false_alerts` section of the catalog. If the violation matches a known false alert AND the `condition` is met (e.g., single-component run, specific component version), inform the user:

> "This is likely a known false positive: {title}. {condition}. No action needed unless the condition doesn't match your case."

### 3. Present the fix

From the matching catalog entry, present **in this order**:
- **Triage note** (if present) — the `triage_note` field is a short, context-aware "first thing to check" for RHOAI. **Always lead with this** — it answers the most common question ("why am I seeing this?") before diving into the full runbook. If the triage note fully answers the user's question, you can stop there and offer to show full details on request.
- **Title and description** — what the violation means
- **Classification** — who typically owns this (`typical_owner`), effort level, whether a rebuild is needed
- **Fix steps** — the ordered `fix_steps` from the catalog, including references/links
- **Rebuild reminder** — if `requires_rebuild: true`, always remind the user that a Konflux rebuild is needed after the fix for the violation to clear

### 4. Handle mixed-path violations

For violations classified as `resolution_path: mixed` (e.g., `rpm_signature.allowed`):
- Present the code-fix options FIRST
- Then note that if code fixes are not feasible, an exception may be needed
- Provide the `exception_context.when_to_exception` text explaining when an exception is appropriate

### 5. Escalation to conforma-exception

If the user determines the fix is not feasible within the release timeline, escalate:

> "Since this violation cannot be resolved in code within the timeline, use the `conforma-exception` skill to create a policy exception. The exception template category for this violation is: {exception_template_category}."

## Direct Invocation vs From-Analyze Path

This skill handles two invocation patterns:

- **From conforma-analyze**: The violation is already identified (rule code known). Look it up directly in the catalog.
- **Direct invocation** (e.g., "fix the hermetic build violation in model-registry"): Use the `aliases` field to resolve the user's phrase to a catalog entry, then proceed with the fix workflow.

## Operational Issues

For violations classified as `type: operational_issue` (e.g., "No Conforma report in Slack", "Version label mismatch"):
- These are NOT conforma policy violations — they're infrastructure/workflow issues
- Present the `fix_steps` which describe the operational troubleshooting procedure
- These cannot be resolved via conforma-exception (no rule code to waive)

## Status

This skill provides catalog-driven guidance. Future versions will include automated fix scripts for simpler violation types (e.g., updating task bundle SHAs, setting hermetic=true).
