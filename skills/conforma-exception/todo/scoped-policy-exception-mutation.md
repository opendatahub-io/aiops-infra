# Scoped policy exception mutation

Status: **NOT STARTED**

Plan: [aiops-infra shared Conforma policy exception matcher and scoped mutation](/home/wznoinsk/.claude/plans/aiops-infra-shared-conforma-policy-exception-matcher.md)

## Goal

Extend and remove component-scoped policy exceptions safely using YAML
structure, while preserving comments, metadata, quote style, and unrelated
components.

## Required behavior

- Match the exact normalized exception value and source entry.
- Group requested components only when all exception details match.
- Split partial extensions into a sibling entry and remove selected components
  from the original entry.
- Preserve already-covered components and create separate entries for new
  components.
- Ask for confirmation when a broader no-expiry exception exists.
- Notify the user that a broader exception exists and that a selected action
  affects only the component-scoped entry.
- Stop on materially ambiguous duplicate entries.
- Remove only requested component names; delete the entry when none remain.
- Refuse automatic component-specific mutation of unscoped or image-only
  entries.
- Never depend on indentation-based regular-expression block editing.
- Use an explicit preview/apply contract with stable choice identifiers,
  revision and entry fingerprints, one staged atomic write for a batch, and no
  write during preview or dry-run.
- Re-read and revalidate the selected policy file immediately before applying
  any change; fail closed if it changed.

## Verification

- Test varied indentation, comments, key order, quote style, and metadata.
- Test grouped extensions, partial extensions, uncovered components, no-expiry
  supersets, user choices, ambiguous matches, and failed confirmations.
- Test single-component and final-component removal.
- Test unscoped and image-only refusal paths.
- Test stale previews, dry-run modernization, batch atomicity, and fail-closed
  missing-policy or pending-confirmation results.
- Maintain at least 97 percent line and branch coverage for modified scripts.
