# Extract exception components and extra arguments in expiry TODOs

Status: **NOT STARTED**

## Goal

Make the Conforma resolution guide's exception-expiry TODO accurately identify
the affected components and preserve any additional exception arguments that
appear on the same line as the violation rule.

## Problem

TODO #2 currently groups expiring exceptions by rule and can omit the component
scope and same-line arguments from the rendered entry. This makes it difficult
to determine which components are protected by an exception and whether the
exception includes additional matching constraints.

## Scope

- Inspect the exception parsing and expiry TODO rendering path used by
  `conforma-analyze`.
- Extract component scope from each exception entry and render it in TODO #2.
- Parse and preserve extra arguments attached to the rule on the same line,
  when present, without treating them as part of the rule name.
- Support entries with no extra arguments without adding empty or misleading
  placeholders.
- Keep separate exception entries distinguishable when they share a rule but
  differ by component or extra arguments.
- Preserve deterministic ordering and the existing expiry-date and days-left
  calculations.

## Verification

- Add unit tests for:
  - an expiring exception with one or more components;
  - an expiring exception whose rule has same-line extra arguments;
  - multiple entries sharing a rule but differing in component or arguments;
  - an entry without extra arguments;
  - the generated TODO #2 table and its rendered component/argument text.
- Run the focused `conforma-analyze` coverage and resolution-guide tests.
- Run the presentation validation script and confirm the generated TODO table
  remains valid Markdown.

## Definition of done

- TODO #2 shows the affected component scope for every expiring exception.
- Same-line extra arguments are displayed accurately and separately from the
  rule name when they exist.
- Exceptions with different scope or arguments are not incorrectly merged.
- Existing expiry calculations and unrelated TODO sections remain unchanged.
- Automated tests cover the supported exception shapes and pass.
