# Move generic expiring exceptions from TODO/DONE to warnings

Status: **NOT STARTED**

## Goal

Change the Conforma Analyze Resolution Guide and complete TODO/DONE preview so
generic exception-expiry records are presented as informational warnings after
the `## DONE` section, rather than as actionable TODO items or completed DONE
items.

## Problem

The generic exception-expiry view lists exceptions based only on their expiry
date. It does not consider the planned release date for the relevant RHOAI
version or product version. These records are useful context, but they are not
the same as the release-date-aware expiry checks already represented in the
TODO sections. Keeping both views in TODO/DONE makes the report imply that the
generic records are actionable work or completed violation coverage, and can
make their counts appear inconsistent with the violation report.

## Required behavior

- Add a dedicated `## WARNINGS` section after the complete `## DONE` section in
  the generated TODO/DONE preview and Resolution Guide.
- Move every generic exception-expiry record into that warning section,
  including records whose exceptions have already expired and records that are
  merely expiring soon.
- Keep the existing release-date-aware exception checks in TODO, including the
  checks that determine whether an exception expires before the planned
  release date.
- Do not place generic expiry records in TODO or DONE.
- Exclude warning records from actionable TODO/DONE counts and from the
  `conforma-violation-accounting` source identity marker. These records do not
  appear in the violation report, so adding them to the violation count would
  produce invalid accounting.
- Preserve deterministic ordering, expiry dates, days-left values, component
  details, extra arguments, and existing empty-state behavior.
- Keep the warning section informational: it must not create, resolve, or
  otherwise imply required remediation work by itself.

## Scope

- Update the canonical key-takeaways/report renderer and any section-ledger
  model needed to distinguish warning records from TODO and DONE owners.
- Update the complete-preview validator so it requires and validates the
  `## WARNINGS` placement without treating warning entries as numbered TODO or
  DONE sections.
- Update the full Resolution Guide assembly so the same warning content is
  present wherever the TODO/DONE block is rendered.
- Update workflow and presentation documentation that currently describes the
  preview as containing only TODO and DONE sections.

## Verification

- Add unit tests covering:
  - a generic expired exception rendered only under `## WARNINGS`;
  - a generic future-expiry record rendered only under `## WARNINGS`;
  - a release-date-aware expiring exception remaining in TODO;
  - warning records excluded from TODO/DONE counts and the accounting marker;
  - warning placement after DONE and before any later guide content;
  - deterministic ordering and empty warning output.
- Update exact-output fixtures and presentation-validator tests for the new
  warning section.
- Run the focused `conforma-analyze` renderer, section-ledger, guide-generation,
  and presentation tests.
- Regenerate a representative Resolution Guide and validate the complete
  preview through the deterministic presentation command.

## Definition of done

- Generic expiry records appear in `## WARNINGS` after `## DONE` and nowhere in
  TODO or DONE.
- Release-date-aware expiry records remain actionable in TODO.
- Warning records do not alter violation, TODO, or DONE accounting.
- The Resolution Guide and chat preview use the same deterministic warning
  representation.
- Existing component, extra-argument, expiry-date, and days-left details remain
  intact.
- Focused and full relevant tests pass, including the repository coverage
  requirements for modified testable code.
