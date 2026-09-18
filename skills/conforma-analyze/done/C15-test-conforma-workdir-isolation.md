# C15 — Isolate Conforma test workdirs from the real home directory

Status: **DONE**

## Goal

Ensure unit tests never depend on or write to the developer's real
`~/.conforma` directory. Every test that creates, discovers, or updates an
active Conforma run must use a temporary work directory.

## Problem

Several unit tests call production entry points that persist step state through
`conforma_context_ops.update_step()`. Without a temporary `CONFORMA_WORKDIR`,
active-run discovery falls back to `~/.conforma`, which may be read-only, stale,
or contain another workflow's active run. One context test directly constructs
`Path.home() / ".conforma"` and also writes there.

The affected tests observed in the coverage run are:

- `tests/unit/test_conforma_analyze_violations_coverage.py::TestOutputFlag::test_output_writes_valid_json_to_file`
- `tests/unit/test_conforma_context_ops.py::TestCreate::test_contracts_home_in_run_dir`
- `tests/unit/test_conforma_report_fetch_fetch_csv_reports.py::TestMainRequiresReleasesOrAll::test_all_flag_triggers_auto_detection`
- `tests/unit/test_conforma_report_fetch_fetch_csv_reports.py::TestMainRequiresReleasesOrAll::test_releases_flag_works`
- `tests/unit/test_conforma_tooling_health_check_tooling_health.py::TestCLIOutput::test_writes_json_file`
- `tests/unit/test_verify_conforma_prerequisites.py::TestOptionalChecks::test_all_pass_returns_zero`
- `tests/unit/test_verify_conforma_prerequisites.py::TestOptionalChecks::test_optional_fail_still_returns_zero`
- `tests/unit/test_verify_conforma_prerequisites.py::TestOptionalChecks::test_required_fail_returns_one`
- `tests/unit/test_verify_conforma_prerequisites.py::TestOptionalChecks::test_json_mode_ignores_optional_failures`
- `tests/unit/test_verify_conforma_prerequisites.py::TestFormatMarkdown::test_main_markdown_format`

## Implementation plan

1. Add an autouse fixture in `tests/conftest.py` that sets
   `CONFORMA_WORKDIR` to a per-test `tmp_path` directory.
2. Ensure the fixture is applied before test code invokes active-run
   discovery, and does not change production defaults.
3. Rewrite the direct `Path.home() / ".conforma"` test to construct its test
   run under `tmp_path` while still verifying home-path contraction behavior.
4. Search for other direct `Path.home() / ".conforma"` writes and active-run
   assumptions outside the listed tests.
5. Keep tests that intentionally validate environment-variable precedence
   explicit: they should set and restore their own `CONFORMA_WORKDIR` values.

## Verification

- Run all affected test modules.
- Run `python -m pytest tests/unit/ -q`.
- Run `python tests/check_script_coverage.py` and confirm every target remains
  above the strict `>97%` threshold.
- Confirm no test creates files under the real `~/.conforma` directory.
- Run the path-reference and workflow-determinism checks if test/documentation
  paths change.

## Definition of done

- Unit tests use temporary Conforma workdirs by default.
- No unit test writes to or depends on the developer's active
  `~/.conforma/.conforma-active` run.
- Tests that validate tilde contraction do so without creating real home
  directory state.
- Full unit tests and the per-script coverage gate pass in a read-only-home
  environment.

## Results

- Added an autouse `isolated_conforma_workdir` fixture in
  `tests/conftest.py`; each test now receives a temporary `CONFORMA_WORKDIR`.
- Updated the tilde-contraction test to use a temporary fake home directory
  instead of writing to the real home directory.
- Affected tests: `263 passed`.
- Full unit suite: `2728 passed, 5 skipped`.
- Coverage gate: all four targets passed the strict `>97%` threshold;
  `scripts/conforma_jira_ticket_ops.py` remained at `97.8%`.
- Ruff, workflow-determinism, and path-reference checks passed.
