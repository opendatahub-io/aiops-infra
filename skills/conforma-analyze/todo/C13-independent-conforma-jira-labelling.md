# C13 — Independently label Conforma-related Jira tickets

Status: **DONE**

Depends on: C11; C14 later broadens the candidate set

## Goal

Add an independent Jira-labelling action that finds Jira tickets related to
Conforma analysis or Conforma violations and ensures the applicable labels are
present:

- `conforma` for tickets related to the Conforma workflow or tooling;
- `conforma-violation` when the ticket represents a specific Conforma
  violation or remediation.

This action must run regardless of whether Jira ticket creation, Jira sync,
coverage discovery, or any other Jira action ran successfully.

It may initially label tickets already found by the current Jira coverage
discovery. Once C14 is implemented, this same action must automatically consume
C14's broader candidate/evidence output during the standard workflow, while
still showing proposed writes and requiring confirmation before applying them.

## Why this is separate

Ticket creation and sync are not reliable prerequisites for labelling. A
pre-existing or externally created ticket can be related to Conforma while
having no label. For example, investigate why
[RHOAIENG-88509](https://redhat.atlassian.net/browse/RHOAIENG-88509) was not
labeled. Possible causes include the ticket predating the current workflow,
the ticket being found only by a non-label search, a failed sync, or labelling
being incorrectly coupled to ticket creation. The implementation must collect
evidence and report the actual cause; it must not assume one.

## Scope

- Define deterministic discovery inputs: current violations, open and closed
  related tickets, known ticket links, summaries/descriptions, comments, and
  the active release/component context.
- Discover label-less historical tickets as well as tickets created during the
  current run. Label-first discovery alone is insufficient for this action.
- Classify whether each found ticket needs `conforma`, `conforma-violation`, or
  both, with the reason and matching evidence recorded.
- Make labelling idempotent and additive: preserve unrelated existing labels
  and never remove labels as part of this action.
- Run as its own workflow step with its own status, error handling, and context
  key. It must not be skipped when creation or sync is disabled, fails, or
  produces no tickets.
- Treat Jira authentication and API failures as explicit failures. Do not
  silently report an empty set or claim that all tickets were labeled.
- Preserve confirmation-before-action: show the proposed ticket/label changes
  before applying Jira writes.

## Questions to resolve

1. What authoritative signals distinguish a general Conforma ticket from a
   `conforma-violation` ticket?
2. Should discovery search all RHOAIENG tickets or a bounded set derived from
   release/component/rule evidence and known links?
3. How should a ticket such as RHOAIENG-88509 be handled when its relationship
   is ambiguous?
4. Should closed tickets be labeled, and are there Jira permissions or rate
   limits that require batching?
5. Should this action run before or after ticket creation in the standard
   workflow, given that it must remain independently runnable?

## Verification

- Unit-test discovery of label-less tickets, label classification, additive
  idempotent updates, API/auth failures, and independence from creation/sync
  results.
- Add a fixture for RHOAIENG-88509 once its current fields and relationship
  evidence are retrieved through the deterministic Jira workflow.
- Verify that no unrelated labels are removed and that no write occurs before
  confirmation.
- Run a live read-only audit first; only apply labels after explicit user
  confirmation.

## Definition of done

- The standard workflow always schedules this independent labelling action.
- It also works as a standalone read-only audit and write operation.
- Tickets returned by the available discovery sources can be labeled even when
  they are currently missing the applicable labels. Broader label-less ticket
  discovery remains the C14 responsibility.
- When C14 is available, its candidates are passed into this action without
  requiring ticket creation or Jira sync to run.
- Each proposed/applied label has an auditable reason and source evidence.
- Creation/sync failures do not prevent labelling, and labelling failures are
  reported independently.
- Tests and workflow documentation cover the independent action.

## Results

- Added `label-conforma-tickets` to `scripts/conforma_jira_ticket_ops.py`.
- The default command is read-only and emits a deterministic label plan plus
  the confirmation question; `--apply` performs additive set-then-verify
  updates.
- The action reads current violation context when available, but does not read
  `jira_sync.json` and does not depend on ticket creation or Jira sync.
- Results are written to `jira_labelling.json` and `steps.jira_labelling`.
- Added workflow integration before Jira ticket creation and unit coverage for
  planning, successful application, verification, partial failure, and CLI
  dispatch.
- Focused test suite: `104 passed`; workflow determinism, path-reference, and
  Ruff checks passed. The repository coverage gate reports
  `scripts/conforma_jira_ticket_ops.py` at `97.8%` (`PASS`); all four gated
  scripts pass the strict `>97%` threshold.
