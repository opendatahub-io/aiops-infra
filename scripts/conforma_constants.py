"""Shared constants for the conforma-reporter repository. No dependencies."""

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
