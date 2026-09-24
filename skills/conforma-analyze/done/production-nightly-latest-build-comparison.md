# Compare production nightly violations with the latest build

Status: **DONE**

Implementation plan: [2026-09-24-conforma-nightly-latest-comparison-plan.md](../../../.agents/plans/2026-09-24-conforma-nightly-latest-comparison-plan.md)

## Goal

Make `conforma-analyze` use fixed Conforma Reporter CSV locations for the
production nightly report and the stage latest-build report, then identify
production violations that no longer appear in the latest build.

Both reports must come from the same Conforma Reporter release branch. The
comparison is gated by the explicit run context values `environment` and
`build_type`:

- The primary report must be `environment: prod` and `build_type: nightly`.
- The comparison report must be `environment: stage` and `build_type: latest`.

## Fixed report locations

The implementation must hardwire these report files:

- Production nightly report:
  `prod/future/build_type_nightly/conforma-violations-report.csv`
- Stage latest-build report:
  `stage/future/build_type_latest/conforma-violations-report.csv`

The production nightly run must also resolve the production resolution guide
from the same branch at:
`prod/conforma-resolution-guide.md`.

Do not use the existing fallback order for this comparison. The production
nightly report is the authoritative input when the analysis is running from a
built nightly report, and the stage report is the only latest-build comparison
input.

## Report-fetch integration

Extend `conforma-report-fetch` when necessary so this behavior is exposed by
clear, deterministic parameters and recorded in the run context. The fetch
workflow must:

- accept or derive the explicit `environment` and `build_type` values;
- fetch the production nightly CSV and production resolution guide from the
  same release branch when gated as `prod` plus `nightly`;
- fetch the stage latest-build CSV from the same release branch when gated as
  `stage` plus `latest`;
- record the selected paths, branch, commit metadata, and build type in
  `context.yaml`;
- fail on any fetch, authentication, path, or metadata error; and
- avoid falling back to another build type or environment.

## Required behavior

- Detect when `conforma-analyze` is running for the built production nightly
  report.
- In that mode, load the production nightly and stage latest-build CSV files.
- Require the explicit `environment: prod` and `build_type: nightly` gate for
  the primary report and the corresponding `environment: stage` plus
  `build_type: latest` metadata for the comparison report.
- Compare violations using the same normalized identity used by the existing
  analysis, including the component and violation details needed to
  distinguish separate violations.
- Find violations present in the production nightly report but absent from the
  stage latest-build report.
- Add a new actionable TODO #1 section when such violations are found. TODO #1
  is reserved for this comparison work; if Tooling is also TODO, Tooling stays
  TODO #0.
- State in the section that each listed violation does not appear in the latest
  build.
- The TODO section must instruct the operator to rerun the product nightly
  build and rerun the Conforma Reporter GitHub workflow for that build.
- Do not emit this comparison TODO for runs that do not pass the explicit
  production-nightly gate.
- Surface missing, unreadable, or malformed CSV inputs as deterministic errors;
  do not silently treat a missing latest-build report as proof that all
  violations disappeared.

## Verification

- Test that the two fixed paths are selected for the intended production
  nightly comparison.
- Test that the comparison is enabled only for the explicit production-nightly
  gate and same-branch stage-latest comparison metadata.
- Test that the production resolution guide is resolved from
  `prod/conforma-resolution-guide.md` on that branch.
- Test that report-fetch does not fall back to another environment or build
  type.
- Test that a violation present in the production nightly CSV and absent from
  the stage latest-build CSV appears in the new TODO section.
- Test that a violation present in both reports is not listed as missing from
  the latest build.
- Test that component and violation-detail differences remain distinguishable.
- Test that the comparison TODO is omitted outside the production nightly
  execution mode.
- Test missing and malformed comparison files and confirm the deterministic
  error is surfaced.
- Run the focused `conforma-analyze` tests and presentation validation.

## Definition of done

- Production nightly analysis reads only the production nightly CSV named
  above.
- The latest-build comparison reads only the stage latest-build CSV named
  above.
- The production nightly artifact is validated against
  `prod/conforma-resolution-guide.md` on the same release branch.
- Newly absent violations are rendered in their own actionable TODO section.
- That section is always assigned TODO #1.
- The rendered instruction explicitly requests a product nightly rebuild and
  a Conforma Reporter GitHub workflow rerun.
- Existing report analysis and TODO sections remain unchanged when the
  comparison does not apply or finds no newly absent violations.
