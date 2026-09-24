# Rework the Conforma resolution report into TODO and DONE sections

Status: **DONE — IMPLEMENTED AND VERIFIED**

## Goal

Rework the Conforma resolution report so it separates outstanding work from
completed or already-covered findings. Render all actionable TODO sections
first, followed by DONE sections, while keeping CSV-reported violations
visible for completeness even when an existing policy exception or merged
request covers them.

## Hard visibility requirement

Every defined report section must always be present in the resolution guide.
Sections must never be omitted because their count is zero, because they are
not actionable, or because another section contains more important findings.
The renderer must show the section's explicit status and zero/healthy state so
that a smaller language model cannot infer that an absent section was
accidentally summarized away.

The implementation must use a fixed, documented section inventory and render
each inventory entry exactly once. It must not rely on conditional section
creation, prose summaries, or a variable list of headings. TODO and DONE are
status groupings within that complete inventory:

- A section with outstanding work is rendered under TODO.
- A section with no outstanding work is rendered under DONE.
- The covered-reported-violations section is always rendered under DONE, with
  an explicit zero-count state when no covered CSV violations exist.
- Tooling is always rendered: as TODO #0 when unhealthy, or as a DONE
  section when healthy.

The full resolution guide and the presented TODO/DONE preview must contain the
same complete section inventory. Presentation code must preserve the
generated section bodies verbatim and must not summarize, collapse, or drop
DONE sections.

The fixed inventory is: Tooling health; violations without an exception or
open Merge Request; exceptions expiring within 14 days; expiring exceptions
without an open Merge Request; expiring exceptions whose open Merge Request
expires before release; expiring exceptions whose open Merge Request extends
past release; violations with an open Merge Request expiring before release;
violations addressed by open Merge Requests not yet merged; warnings becoming
violations before release; and warnings becoming violations after release.

## Required ordering and classification

1. **TODO sections** come first. Every section with work to do is rendered
   here; no actionable section may be omitted.
   - Tooling is `TODO #0` when the Conforma reporter workflow is unhealthy or
     otherwise requires investigation.
   - Other sections retain their existing deterministic order when they
     contain violations or another actionable item.
2. **DONE sections for covered reported violations** come immediately after
   the actionable TODO sections and are always visible.
   - Include violations that were actually reported in the CSV.
   - Keep them visible even when an existing policy-file rule or merged
     request already covers them.
   - Label and explain the coverage source so “reported but covered” is not
     confused with “no violations were reported.”
3. **DONE sections for empty former TODO categories** come after the covered
   violation section and are always visible.
   - Convert every currently defined TODO category with zero violations and
     zero actionable items into a DONE section.
   - Healthy Tooling is a DONE section, not a TODO section.
   - Preserve the section's useful zero-count or healthy-status evidence.

## Scope

- Identify the canonical section model and classification data used by the
  resolution-guide and TODO-preview renderers.
- Add a deterministic TODO/DONE classification layer over a fixed section
  inventory that preserves section ordering and assigns Tooling `#0` only
  when Tooling is actionable.
- Render covered CSV violations as DONE evidence without dropping them from
  the report or incorrectly counting them as remaining work.
- Render zero-work former TODO sections as DONE after covered findings.
- Ensure the full resolution guide and the presented TODO/DONE preview use the
  same classification and ordering contract.
- Update presentation validation, link validation, workflow documentation,
  and any report structure rules that currently require a fixed set of TODO
  sections.
- Keep the report deterministic when sections move from TODO to DONE; no
  section may be omitted, reordered, summarized, or collapsed.

## Resolved implementation contract

TODO and DONE numbering is independent and starts at `#0`; Tooling is always
`TODO #0` when unhealthy, incomplete, or unknown, and `DONE #0` only when
healthy. The covered-reported-violations evidence section is always present in
DONE and is the first non-Tooling DONE section. Empty former work sections
follow it in their fixed inventory order.

Every section has a stable marker immediately before its heading:
`<!-- conforma-section: <stable-id> -->`. Validators must use these markers,
not prose titles, to enforce exact inventory, status, order, and one-time
rendering. The full guide and `conforma-todo-and-done.md` must contain the
same complete marked block byte-for-byte.

Source CSV violations are normalized to `(violation code, component, semantic
detail)` identities, with `full_violation_code` retained for policy matching.
Each identity has exactly one owner section. Expiry and warning sections may
contain secondary references to an owned identity, but secondary references
must not increase the source-violation total. The generator must fail closed
when an identity has no owner, more than one owner, or is absent from the
rendered accounting. Exception and warning work-item counts are separate
metrics and must not be compared directly with source CSV violation counts.

Any missing release date, missing coverage input, absent or malformed tooling
health, or evaluation error is an explicit TODO condition with diagnostic
evidence. It is never a DONE or not-applicable result.

## Implementation notes

- A section containing both covered and uncovered identities retains the
  actionable rows in TODO and the policy-covered rows in the covered DONE
  evidence section. Open Merge Request coverage remains TODO until merged.
- Policy coverage must include deterministic evidence sufficient to match the
  retained full violation code and component; unknown or incomplete evidence
  remains TODO.
- Tooling diagnostics remain visible in either status, with the status decided
  only by deterministic health evidence.
- Summaries must distinguish reported source violations, policy-covered
  violations, outstanding violations, and exception/warning work-item counts.

## Verification

- Add unit tests for:
  - unhealthy Tooling as TODO #0;
  - healthy Tooling as DONE;
  - every defined section being present when its count is zero;
  - a report with only actionable TODO sections;
  - CSV violations covered by an existing policy rule or merged request,
    retained as DONE evidence;
  - zero-violation former TODO sections rendered as DONE;
  - mixed covered and actionable findings;
  - no-work reports with no TODO sections;
  - identical complete section inventory and ordering in the full guide and
    TODO/DONE preview;
  - presentation output retaining every DONE heading and body verbatim.
- Update exact-output and presentation-validation tests for variable TODO and
  DONE section counts.
- Generate representative guides and verify that all section links resolve
  and that no reported CSV violation disappears merely because it is covered.
- Run focused Conforma analysis tests and the repository's applicable
  coverage and documentation checks.

Implementation verification: the focused TODO/DONE suite passes; the full unit
suite passes for this feature, with one unrelated pre-existing broken-link
failure in `skills/conforma-remedy/todo/README.md` and
`skills/conforma/todo/README.md`.

## Definition of done

- Actionable sections are the only sections under TODO, with Tooling at #0
  when unhealthy.
- Every defined section is always present exactly once, including zero-count
  and healthy sections.
- Covered CSV-reported violations remain visible in DONE sections.
- Empty former TODO sections, including healthy Tooling, appear under DONE.
- DONE sections always follow all TODO sections.
- Full guides, TODO/DONE previews, validators, and documentation agree on the
  same deterministic structure.
- Automated tests cover the classification, ordering, rendering, and
  validation behavior.
