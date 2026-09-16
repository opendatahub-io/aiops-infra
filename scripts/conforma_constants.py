"""Shared constants for the conforma-reporter repository. No dependencies."""

# ---------------------------------------------------------------------------
# Context confirmation table — shared row labels and placeholders.
#
# The context confirmation table is shown in Step 2 (resolve_release_context)
# and re-emitted in the Step 9 resolution guide metadata header
# (guide_renderers.render_metadata_header). Both steps must render the same
# table structure: rows whose values are not known yet carry a placeholder
# note in Step 2 and are replaced in place once the values become available.
# The guide renderer matches each row by its *label* (ROW_LABEL_*), so only
# the labels must stay stable; the placeholder *values* are free to carry a
# short note about when the real value will appear, so the Step 2 table does
# not read as an error. Keep the labels and placeholders here so the two
# renderers cannot drift.
# ---------------------------------------------------------------------------
ROW_LABEL_GENERATED = "Generated"
ROW_LABEL_SOURCE_CSV_ROWS = "Source CSV rows (raw, per-image)"
ROW_LABEL_TOTAL_VIOLATIONS = "Total violations (deduplicated per image)"
ROW_LABEL_SOURCE_CSV_GENERATED = "Source CSV generated"
# Placeholder shown in Step 2 for each value that is not known yet. Each one
# tells the user the step at which the value becomes available so the pending
# rows read as "expected, will fill in shortly" rather than as an error.
NOT_YET_AVAILABLE_NOTE = "set when the resolution guide is generated (step 9)"
NOT_YET_AVAILABLE_SOURCE_CSV_GENERATED_NOTE = "set after the source CSV is fetched (step 4)"
NOT_YET_AVAILABLE_SOURCE_CSV_ROWS_NOTE = "set after the source CSV is fetched (step 4)"
NOT_YET_AVAILABLE_TOTAL_VIOLATIONS_NOTE = "set after the violations are analyzed (step 6)"


CONFORMA_REPORTER_REPO = "red-hat-data-services/conforma-reporter"
CONFORMA_REPORTER_URL = f"https://github.com/{CONFORMA_REPORTER_REPO}"
CONFORMA_REPORTER_ACTIONS_URL = (
    f"{CONFORMA_REPORTER_URL}/actions/workflows/conforma-reporter.yaml"
)

RAW_DOWNLOAD_BASE = "https://raw.githubusercontent.com"
GITHUB_API = "https://api.github.com"

CSV_FILENAME = "conforma-violations-report.csv"
WARNINGS_CSV_FILENAME = "conforma-warnings-report.csv"
RESOLUTION_GUIDE_FILENAME = "conforma-resolution-guide.md"
TODO_PREVIEW_FILENAME = "conforma-todo.md"

CSV_PATHS = [
    f"prod/future/build_type_latest/{CSV_FILENAME}",
    f"prod/future/build_type_nightly/{CSV_FILENAME}",
    f"prod/release_day/{CSV_FILENAME}",
]

WARNINGS_CSV_PATHS = [
    f"prod/future/build_type_latest/{WARNINGS_CSV_FILENAME}",
    f"prod/future/build_type_nightly/{WARNINGS_CSV_FILENAME}",
    f"prod/release_day/{WARNINGS_CSV_FILENAME}",
]

STAGE_CSV_PATHS = [
    f"stage/future/build_type_latest/{CSV_FILENAME}",
    f"stage/future/build_type_nightly/{CSV_FILENAME}",
]

STAGE_WARNINGS_CSV_PATHS = [
    f"stage/future/build_type_latest/{WARNINGS_CSV_FILENAME}",
    f"stage/future/build_type_nightly/{WARNINGS_CSV_FILENAME}",
]

# ---------------------------------------------------------------------------
# Jira discovery (conforma-analyze) — single source of truth for the label-first
# discovery scope. On the redhat.atlassian.net tenant only the PLURAL
# ``labels in (...)`` / ``labels = "..."`` forms return data; the singular
# ``label in (...)`` silently returns empty. The builder below always emits the
# plural form and applies NO status filter (discovery must see both open and
# closed tickets — closed ones are prior-issue context).
# ---------------------------------------------------------------------------
CONFORMA_DISCOVERY_PROJECTS = ["RHOAIENG", "PSX", "OCPEXCEPT", "PRODSECRM", "RHAI", "RHAIENG", "AIPCC"]
CONFORMA_DISCOVERY_LABELS = ["conforma", "conforma-violation", "conforma-exception-ai-skill"]

VERIFY_NEXT_STEP = (
    f"Run [conforma-reporter]({CONFORMA_REPORTER_ACTIONS_URL})"
    " or `conforma-violations-scan` AI skill"
    " to verify the violation is no longer reported"
)


def csv_paths_for_environment(environment: str) -> list[str]:
    """Return CSV fallback paths for the given environment."""
    if environment == "stage":
        return STAGE_CSV_PATHS
    return CSV_PATHS


def warnings_csv_paths_for_environment(environment: str) -> list[str]:
    """Return warnings CSV fallback paths for the given environment."""
    if environment == "stage":
        return STAGE_WARNINGS_CSV_PATHS
    return WARNINGS_CSV_PATHS


def build_report_url(release: str, environment: str) -> str:
    """Build a GitHub URL to the violations report for a release."""
    paths = csv_paths_for_environment(environment)
    return f"{CONFORMA_REPORTER_URL}/blob/{release}/{paths[0]}"


def build_warnings_report_url(release: str, environment: str) -> str:
    """Build a GitHub URL to the warnings report for a release."""
    paths = warnings_csv_paths_for_environment(environment)
    return f"{CONFORMA_REPORTER_URL}/blob/{release}/{paths[0]}"


def build_label_discovery_jql(
    projects: list[str] = CONFORMA_DISCOVERY_PROJECTS,
    labels: list[str] = CONFORMA_DISCOVERY_LABELS,
) -> str:
    """Build the label-first Jira discovery JQL across the conforma projects.

    Uses the plural ``labels in (...)`` form (the only form that returns data on
    this tenant) and applies NO status filter, so both open and closed tickets
    are discovered. Closed tickets are surfaced downstream as prior-issue context.
    """
    project_list = ", ".join(projects)
    label_list = ", ".join(labels)
    return f"project in ({project_list}) AND labels in ({label_list})"
