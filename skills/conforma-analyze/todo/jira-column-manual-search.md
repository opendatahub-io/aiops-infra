# Include manual Jira search guidance in TODO tables

Status: **NOT STARTED**

## Goal

Include the literal guidance `try manual search` in the Jira column of every
TODO-section table when automated Jira discovery has no ticket or create link
to show.

## Scope

- Update the deterministic TODO-table renderer for every section that has a
  Jira column.
- Preserve existing Jira ticket, create-link, and related-search output when
  automated results are available.
- Keep non-TODO Jira tables unchanged unless the final implementation shows
  that they share the same renderer and cannot be separated cleanly.

## Verification

- Add unit coverage for an empty Jira result in each TODO-table shape.
- Confirm existing ticket and create-link cells remain unchanged.
- Regenerate a resolution guide and verify every applicable TODO Jira cell
  contains the requested guidance when no automated result exists.

## Definition of done

- Every applicable TODO-section Jira column provides `try manual search` when
  automated Jira discovery has no result.
- Existing automated Jira results remain intact.
- Unit tests pass.
