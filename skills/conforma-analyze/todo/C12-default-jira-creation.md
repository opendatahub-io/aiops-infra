# C12 — Enable Jira ticket creation by default

Status: **NOT STARTED**

Depends on: C14 — robust broad discovery and matching of existing Jira tickets

## Goal

Make creation of Conforma violation Jira tickets the default behavior of the
standard `conforma-analyze` workflow only after C14 provides robust discovery
of existing tickets, subject to the existing confirmation before any external
write. Users should not need to discover or enable a separate opt-in flag for
the normal analysis path.

## Scope

- Define which violation groups produce tickets by default and which existing
  open or covered tickets suppress duplicate creation. This decision must use
  C14's broad candidate and evidence results, not only label-first discovery.
- Preserve the confirmation-before-action rule: analysis and proposed ticket
  content must be shown before Jira creation is attempted.
- Make the default explicit in workflow documentation, command arguments, and
  context handover data.
- Keep dry-run and read-only discovery behavior available for validation.
- Surface Jira authentication, creation, and partial-failure errors without
  silently continuing as if tickets were created.
- Record created ticket keys, skipped duplicates, and failed attempts in the
  run context and resolution guide.

## Questions to resolve

1. Does “default” mean enabled after user confirmation in the standard full
   analysis, or enabled without a second confirmation after the first analysis
   confirmation? The latter would violate the repository confirmation policy.
2. Which violation classes should never create a ticket automatically, such as
   insufficient-evidence or transient operational diagnoses?
3. How should a partial creation failure affect later guide generation and the
   final workflow status?

## Verification

- Unit-test default argument/context behavior, confirmation boundaries,
  duplicate suppression, partial failures, and context persistence.
- Validate workflow-determinism and documentation-reference checks.
- Perform a live read-only discovery/dry-run; do not create real Jira tickets
  without explicit user confirmation.

## Definition of done

- The standard workflow clearly enables Jira creation by default.
- C14 runs before creation decisions and supplies existing-ticket matches,
  including label-less and ambiguous candidates.
- No Jira write occurs before the required confirmation.
- Read-only and dry-run paths remain deterministic.
- Success, skip, and failure states are visible in the context and generated
  resolution guide.
- Tests and workflow documentation are updated.
