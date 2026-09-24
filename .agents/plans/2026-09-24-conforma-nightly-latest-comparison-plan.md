# Conforma Nightly/Latest Violation Comparison Implementation Plan

> **For agentic workers:** Implement this plan task-by-task with a fresh test
> cycle after each task. Preserve the repository's deterministic workflow and
> present generated script output verbatim.

**Goal:** Compare a production nightly Conforma report with the stage latest
build on the same release branch and render violations absent from the latest
build as actionable TODO #1 work.

**Architecture:** Add explicit `build_type` context and deterministic report
selection to the CSV fetcher. Fetch the production nightly CSV and resolution
guide plus the stage latest CSV from the same release branch, record all source
metadata, and fail closed on any missing or malformed input. Pass the latest
build records into the existing guide renderer, reuse its atomic violation
identity, and add a fixed-priority TODO #1 section only for the gated
production-nightly execution.

**Tech Stack:** Python, `requests`, YAML context helpers, Markdown renderer,
pytest.

**Spec:** `skills/conforma-analyze/done/production-nightly-latest-build-comparison.md`

## Global Constraints

- The two CSV reports use the same Conforma Reporter release branch.
- The primary gate is `environment: prod` plus `build_type: nightly`.
- The comparison gate is `environment: stage` plus `build_type: latest`.
- Fixed CSV paths are `prod/future/build_type_nightly/conforma-violations-report.csv` and `stage/future/build_type_latest/conforma-violations-report.csv`.
- The production resolution guide path is `prod/conforma-resolution-guide.md`.
- No fallback across environments or build types is allowed for this workflow.
- Missing, unreadable, malformed, unauthenticated, or incomplete source data fails the deterministic path.
- Comparison identity reuses `(full violation code, component, semantic detail)` through the existing ledger semantics.
- The comparison section is always TODO #1; Tooling remains TODO #0 when applicable.
- New or modified testable code requires unit tests and modified code must meet the repository's applicable 97% coverage gates.

## Review Focus

- A missing `build_type` must not silently enable or disable the comparison; test explicit gate validation.
- A stage latest file must not be replaced by a stage nightly or production latest fallback; test attempted paths.
- A missing production resolution guide must fail the fetch before analysis; test the artifact gate.
- A violation differing only by component or semantic detail must remain a distinct identity; test the ledger comparison.
- TODO #1 must remain stable when Tooling is TODO #0 and when Tooling is DONE; test both numbering states.

### Task 1: Add deterministic build-type report selection and artifact fetching

**Files:**

- Modify: `scripts/conforma_constants.py`
- Modify: `skills/conforma-report-fetch/scripts/fetch_csv_reports.py`
- Modify: `skills/conforma-report-fetch/workflows/csv.md`
- Modify: `skills/conforma-report-fetch/SKILL.md`
- Test: `tests/unit/test_conforma_report_fetch_fetch_csv_reports.py`

**Interfaces:**

- Add explicit `build_type` values `latest` and `nightly`.
- Add `fetch_fixed_report_for_release(release, output_dir, environment, build_type)` returning a structured result with local path, source path, commit date, and commit SHA.
- Add `fetch_resolution_guide_for_release(release, output_dir)` returning the same metadata shape and enforcing `prod/conforma-resolution-guide.md`.
- Add a gated fetch mode that writes `steps.fetch.primary_report`, `steps.fetch.latest_comparison_report`, `steps.fetch.production_resolution_guide`, `steps.fetch.build_type`, and source metadata to context.

- [x] Add failing tests for exact path selection, same-branch fetching, guide fetching, missing build type, and no fallback.
- [x] Implement path constants and explicit build-type validation.
- [x] Implement report and guide fetch helpers with fail-closed commit metadata handling.
- [x] Extend the command-line interface with explicit build-type support while preserving existing ordinary fetch behavior.
- [x] Add gated fetch metadata and context updates.
- [x] Update workflow documentation with the deterministic commands and paths.
- [x] Run `pytest tests/unit/test_conforma_report_fetch_fetch_csv_reports.py -v`.

### Task 2: Load and validate the comparison report in the analysis context

**Files:**

- Modify: `skills/conforma-analyze/scripts/generate_resolution_guide.py`
- Modify: `skills/conforma-analyze/scripts/analyze_csv_report.py` only if a strict CSV validation helper is needed
- Test: `tests/unit/test_conforma_analyze_generate_resolution_guide.py`

**Interfaces:**

- Read the gated report metadata from `steps.fetch`.
- Load the production nightly records as the primary source and the stage latest records as comparison input.
- Pass `latest_build_records` and comparison provenance to `render_key_takeaways`.
- Raise a deterministic error when the production-nightly gate is active but either CSV, guide artifact, build metadata, or source metadata is absent or malformed.

- [x] Add failing tests for the production-nightly gate, non-gated no-op behavior, malformed CSV, missing guide, and same-branch provenance.
- [x] Implement context resolution and strict source validation.
- [x] Load both record sets using the existing CSV parser and preserve full violation code and semantic detail.
- [x] Pass comparison inputs without reconstructing identities from coverage JSON.
- [x] Run the focused generator tests.

### Task 3: Render the fixed TODO #1 comparison section

**Files:**

- Modify: `skills/conforma-analyze/scripts/guide_renderers.py`
- Modify: `skills/conforma-analyze/scripts/violation_section_ledger.py` if its public comparison helper belongs there
- Test: `tests/unit/test_conforma_analyze_generate_resolution_guide.py`
- Test: `tests/unit/test_conforma_analyze_violation_section_ledger.py`

**Interfaces:**

- Add a pure comparison function such as `violations_absent_from_latest(primary_records, latest_records) -> list[dict]` using the existing atomic identity representation.
- Extend `render_key_takeaways(..., latest_build_records=None, comparison_metadata=None)`.
- Emit section marker `latest-build-missing-violations` with priority `1`, `force_todo` only when missing identities exist, and the exact rerun instructions.

- [x] Add failing tests for absent, present, component-different, detail-different, empty, and gated-off inputs.
- [x] Implement set-based identity comparison with deterministic ordering.
- [x] Render one row per absent identity with production rule, component, semantic detail, and latest-build provenance.
- [x] Ensure the section sorts as TODO #1 after Tooling TODO #0 and remains TODO #1 when Tooling is DONE.
- [x] Run the focused renderer and ledger tests.

### Task 4: Update skill workflow and documentation

**Files:**

- Modify: `skills/conforma-analyze/workflows/full-analysis.md`
- Modify: `skills/conforma-analyze/SKILL.md`
- Modify: `skills/conforma-analyze/todo/README.md`
- Modify: `skills/conforma-analyze/done/production-nightly-latest-build-comparison.md`

- [x] Document the gated fetch invocation and context contract.
- [x] Document that TODO #1 means a production nightly violation is absent from the same-branch stage latest report.
- [x] Document fail-closed handling and the required nightly rebuild plus Conforma Reporter workflow rerun.
- [x] Link this implementation plan from the TODO record and update the TODO status only after validation passes.
- [x] Run Markdown/link validation available in the repository.

### Task 5: Full validation and handover

**Files:**

- Test: all affected unit tests and coverage configuration as required by the repository
- Modify: `.agents/plans/2026-09-24-conforma-nightly-latest-comparison-plan.md`

- [x] Run the focused fetch, generator, ledger, renderer, and presentation tests together.
- [x] Run `pytest tests/unit/` and record the exact result.
- [ ] Run applicable coverage checks and confirm the 97% line, branch, and statement requirements for modified code.
- [x] Verify generated output contains the expected fixed source paths, provenance, and TODO #1 behavior.
- [x] Review the final diff for unrelated changes and preserve all pre-existing user modifications.
- [x] Move the TODO document to `skills/conforma-analyze/done/` only after implementation and validation are complete.

## Plan self-review

- Every requirement in the approved TODO maps to Tasks 1–5.
- The existing fallback behavior is explicitly isolated from the new gated path.
- The production guide artifact is treated as a required source-validation input, not as a substitute for the production CSV.
- The comparison reuses existing identity semantics and renderer ordering rather than creating a second TODO numbering system.
- Missing data fails closed at fetch or generation time and cannot be rendered as evidence that a violation disappeared.
- The current repository has unrelated uncommitted changes; implementation must limit edits to the listed files and preserve those changes.

## Validation handover

- Focused feature suite: `315 passed`.
- Full unit suite excluding the pre-existing broken path-reference test:
  `2801 passed, 5 skipped`.
- Full unit suite currently fails only because unrelated existing links are
  broken in `skills/conforma-remedy/todo/README.md`, `skills/conforma/TODO.md`,
  and `skills/conforma/todo/README.md`.
- `git diff --check` passes.
- Coverage thresholds were not run; this remains an explicit follow-up because
  the repository-wide coverage command was not identified in the current task.
