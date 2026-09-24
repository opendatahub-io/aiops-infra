# Shared Conforma Policy Exception Matcher and Scoped Mutation

## Status

Design approved in conversation; written specification awaiting user review.

## Purpose

Conforma analysis and exception management currently discover policy exceptions
through different line-oriented implementations. This causes valid exceptions
to be missed when policy values are quoted, parameterized, indented
differently, or stored in a current policy location such as
`volatileConfig.exclude`.

The immediate symptom is that a violation such as
`base_image_registries.base_image_permitted` can be reported as uncovered even
when parameterized exceptions for the same rule are present in the policy.
The same inconsistency can cause exception-management operations to select the
wrong rule entry or modify a broader exception unintentionally.

The change will establish one shared normalized parser and matcher for policy
exception discovery, then use a YAML-aware round-trip editor for safe,
component-scoped policy mutations.

## Goals

- Recognize exact, quoted, and parameterized policy values consistently.
- Preserve the complete parameterized value and expose the suffix after the
  first `rule:` separator as an extra argument.
- Match a base rule only against the exact rule or values beginning with that
  rule followed by `:`; do not match similarly named rules.
- Match a full parameterized query only against the exact normalized value.
- Preserve every matching exception entry independently, including its
  component scope, image scope, expiry, reference, source file, and source
  location.
- Use the same normalized records for violation coverage, expiring-exception
  reporting, policy exception discovery, and exception-management decisions.
- Support the observed `volatileCriteria` and `volatileConfig.exclude`
  time-bounded policy locations without conflating them with permanent
  exclusions or self-service exception files.
- Extend and remove component-scoped exceptions without relying on indentation
  or regular-expression block deletion.
- Preserve YAML comments, key order, quote style, and unrelated metadata during
  mutations.
- Enforce at least 97 percent line and branch coverage for modified scripts.

## Non-goals

- Changing Conforma policy semantics.
- Treating permanent exclusions as expiring component-scoped exceptions.
- Treating self-service `imageRef` entries as Enterprise Contract policy
  entries.
- Automatically rewriting broad unscoped or image-only exceptions during a
  component-specific operation.
- Publishing or submitting a Merge Request as part of this change.

## Design

### Shared normalized exception records

The shared Conforma policy operations module will own parsing and matching of
time-bounded policy exception entries. Each normalized record will retain
enough information for both reporting and safe downstream decisions:

- normalized full `value`;
- `base_rule` and `extra_argument`;
- `componentNames`, including whether the field was present;
- `imageUrl` and `imageRef` when present;
- `effectiveUntil` and its normalized representation;
- `reference` and other entry metadata;
- source category and policy location;
- repository-relative source file and one-based display line locations;
- the structural path needed by the mutation workflow.

The parser will use YAML structure for policy discovery. It will not assume a
fixed number of spaces before list items. It will retain round-trip YAML nodes
when a mutation operation needs comments and formatting, while reporting
plain normalized records to analysis consumers.

The existing exception-management import surface will remain available through
a compatibility wrapper while both workflows move to the shared parser. The
shared record will use zero-based internal line indexes for existing callers;
reporting adapters will expose one-based display lines. The compatibility
wrapper will retain its current signature and legacy fields until callers are
migrated and covered.

### Matching rules

Values are normalized by removing YAML scalar quoting without altering the
value content. The separator after a base rule is the first colon:

- `rule` matches `rule` and `rule:any-suffix`;
- `rule` does not match `rule-other`;
- `rule:any-suffix` matches only that exact full value;
- suffixes containing registry paths, URLs, query strings, checksums,
  ampersands, or additional colons remain intact.

Every distinct exact value remains a distinct record. Multiple values for one
base rule must not collapse into one coverage or expiry record.

Policy-file searches continue to apply the discovered policy-file allowlist so
an exception from another product cannot cover the requested components.

### Source boundaries

The parser will explicitly recognize the observed structured policy locations:

- the historical `volatileCriteria` policy sequence;
- the current `spec.sources[].volatileConfig.exclude` policy sequence.

Permanent exclusions are read from the separate
`spec.sources[].config.exclude` sequence. A source entry is selected by the
policy file and structural path recorded with the normalized exception; new
entries are inserted into that same sequence rather than appended to an
arbitrary file location.

Permanent `exclude` entries remain a separate permanent-global-exclusion
result. Self-service files under `exceptions/` remain a separate discovery
path with their existing `imageRef` digest handling. Shared normalization may
use common fields, but source category and coverage semantics remain explicit.

### Violation coverage and expiry reporting

Coverage will retain one match per violation value, component, and exact
exception record. It will not deduplicate records only by file, expiry, or
component. Each expiry TODO entry will retain the exact exception value,
extra argument, affected components, expiry, and source location so separate
parameterized entries or dates remain visible.

Coverage output will contain an explicit `exception_matches` collection of
per-entry records. Each record includes a stable match identifier, exact value,
base rule, extra argument, component, component list, expiry, source category,
repository-relative source file, source path, source line, and entry
fingerprint. Aggregate expiry summaries remain available for existing status
tables, but TODO #2 consumes this per-entry collection and never reconstructs
individual exceptions from an earliest date or a first match.

An unscoped exception continues to have global coverage semantics. A
component-scoped exception covers only its listed components. Image-scoped and
self-service records continue to use their existing source-specific matching
rules.

### YAML-aware component mutation

Exception-management mutation will load the selected policy document with a
round-trip YAML implementation. It will locate the structural exception entry
by exact normalized value and the normalized record identity, not by a fixed
indentation or a base-rule-only match.

Every mutation has a preview/apply contract. Preview returns the proposed
action, exact source-entry fingerprint, file revision digest, before/after
component scope, expiry, and required confirmation choices. Apply reloads the
file, recomputes the fingerprint and revision digest, and fails closed if
either has changed. No caller may write, commit, push, or create a Merge
Request until the selected confirmation choice is validated against preview.
For a batch, the preview contains unconditional actions and independent
decision groups. Each decision group has a stable identifier and choices whose
action sets and before/after states are complete. Apply receives one choice
selection per decision group, rejects missing or conflicting selections, and
writes all selected actions atomically. Choosing to keep a broader exception
produces an explicit no-change result for that decision.

When extending a component-scoped entry:

1. Select the requested component subset and exact exception value.
2. If all selected components share the same complete resulting metadata,
   retain them in one entry.
3. If only part of an existing entry is selected, clone the complete mapping
   into a sibling entry, retain only the selected components in the clone, set
   the requested expiry, and remove those components from the original.
4. Components may share the new entry only when the complete details match,
   including the rule value, comments, expiry, reference, image fields, and
   other metadata. Otherwise, keep separate entries.
5. Preserve the complete entry and its annotations on both resulting entries,
   changing only the selected component scope and requested expiry.

If an existing entry covers some requested components but not others, the
already-covered components are handled in their existing scoped entry and the
uncovered components receive a separate entry. An existing component-scoped
exception without an expiry is a broader superset of a requested expiring
exception; it must be reported to the user rather than changed automatically.

When removing components:

- remove only the requested names from a component-scoped list;
- delete the whole entry if no component names remain;
- never leave an empty `componentNames` list that could become an unscoped
  exception;
- refuse automatic component-specific mutation of an unscoped or image-only
  entry and explain why it requires explicit handling.

When a broader exception exists, the user is always told that it exists and
that any selected action affects only the component-scoped entry. The user is
shown these choices in clear language:

1. keep the broader exception and treat the request as already covered;
2. replace or narrow the broader exception, only when the complete replacement
   component scope is supplied and the exact before/after coverage is shown;
3. add the new component-scoped exception while leaving the broader exception
   untouched.

For an unscoped exception, option 2 is refused unless the user supplies the
complete list of components that must remain covered. It requires a separate
confirmation because it can remove coverage from components outside the
request. Without that complete scope, only options 1 and 3 are available.

If multiple entries match the same exact value and component but differ in
expiry, reference, comments, or other material metadata, the workflow stops
and presents the candidates for user selection. It must not choose one
implicitly.

### Error handling

Malformed YAML, unsupported policy locations, missing structural targets,
stale preview fingerprints, ambiguous matches, missing policy data, and
pending confirmation are deterministic failures. The workflow will report the
source file, rule/value, and reason, return a non-success status, and will not
silently fall back to line-based parsing, create a new exception, or partially
mutate a file. Dry-run and preview paths must prove that the target file is
unchanged.

## Alternatives considered

### Keep separate parsers and only align regular expressions

This has the smallest immediate diff but preserves the root cause: analysis
and exception management can still diverge as new policy shapes appear. It
also cannot safely support component splitting and deletion across arbitrary
indentation.

### Create a new standalone exception-domain operations module

This would give parsing, matching, and mutation a clean new boundary, but it
would add another shared interface and require broader migration work. The
existing Conforma policy operations module already owns policy discovery and is
the established shared primitive location.

### Selected approach

Extend the existing shared Conforma policy operations primitive with canonical
normalized parsing and matching. Keep round-trip mutation orchestration in the
exception-management workflow, using the shared record identity and structural
location. This gives both consumers one matching implementation while keeping
policy editing concerns close to the workflow that already performs them.

## Testing and validation

Tests will cover:

- exact, quoted, parameterized, URL-bearing, and multi-colon values;
- base-rule matching boundaries and exact full-value matching;
- historical `volatileCriteria` and current `volatileConfig.exclude` shapes;
- component-scoped, unscoped, image-scoped, permanent, and self-service
  source boundaries;
- multiple exact values for one base rule;
- the RHOAI 3.6 EA1 parameterized base-image exceptions;
- coverage association and expiry TODO rendering;
- extension grouping, partial coverage, split entries, no-expiry supersets,
  ambiguous candidates, and user confirmation choices;
- removal of one component, removal of the final component, and refusal of
  unsafe unscoped/image-only mutation;
- varied indentation, comments, quote styles, key order, and round-trip
  preservation.

The coverage gate will report both line and branch coverage, include every
modified script as a required target, and treat missing coverage data as a
failure. The minimum threshold is inclusive: line and branch coverage must
each be at least 97.0 percent. Missing branch data, missing target files, and
zero-statement targets are failures rather than skips.

Validation will run focused unit tests first, then all affected unit tests,
the coverage gate, and `git diff --check`. No external policy repository,
Jira, GitLab, or Merge Request writes are part of validation.

## Transition to implementation planning

After user review of this specification, the implementation plan will divide
the work into parser and matcher changes, workflow integration, round-trip
mutation behavior, coverage and expiry rendering, tests, and final validation.
The rewritten plan will be independently reviewed before implementation.
