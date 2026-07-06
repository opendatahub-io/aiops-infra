# CSV Violation Reports Workflow

## 1. CSV Violation Reports (GitHub)

> **Staleness warning:** CSV reports are generated on a schedule by the `conforma-reporter` CI job and committed to the repo. They can lag behind the live Konflux state by hours or days. When using CSV data, always inform the user of the report's `created_at` timestamp (returned by the fetch script) so they know how current it is. For the freshest data, use the Tekton JSON mode instead.

Downloads CSV violation reports from each release branch of the private `red-hat-data-services/conforma-reporter` repository via `raw.githubusercontent.com`. Handles multi-megabyte files reliably without GitHub Contents API size limits.

### Prerequisites

See [README.md](README.md) for installation and shared prerequisites.

**Auth check:**

```bash
python3 scripts/verify_conforma_prerequisites.py --fix
```

### Data Source

- **Repo**: `red-hat-data-services/conforma-reporter` (private)
- **Branch per release**: `rhoai-2.25`, `rhoai-3.3`, `rhoai-3.4`, etc.
- **Columns**: `type`, `component_name`, `image`, `message`, `effective_on`, `code`, `title`, `description`, `solution`

The script tries multiple CSV paths within the `prod/` directory in order for both violations and warnings:

**Violations** (`conforma-violations-report.csv`):
1. `prod/release_day/conforma-violations-report.csv` (primary)
2. `prod/future/build_type_latest/conforma-violations-report.csv`
3. `prod/future/build_type_nightly/conforma-violations-report.csv`

**Warnings** (`conforma-warnings-report.csv`, fetched by default):
1. `prod/release_day/conforma-warnings-report.csv` (primary)
2. `prod/future/build_type_latest/conforma-warnings-report.csv`
3. `prod/future/build_type_nightly/conforma-warnings-report.csv`

If `release_day` is unavailable (e.g. for in-development versions), the script automatically falls back to the next available report. Use `--no-warnings` to skip fetching warnings CSVs.

### Usage

```bash
# Auto-detect releases, auto-create ~/.conforma/<timestamp>/:
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py

# Explicit releases:
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py --releases rhoai-2.25,rhoai-3.4

# Explicit output directory (used by conforma-analyze):
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --releases rhoai-3.4 \
  --output-dir /path/to/output

# Skip fetching warnings CSVs:
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py --no-warnings

# Use pre-downloaded CSVs instead of fetching:
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --local-dir /path/to/csvs
```

When `--output-dir` is omitted, the script creates a timestamped directory under `~/.conforma/` (relative to this skill) and updates the `~/.conforma/latest` symlink. The output directory contains `{release}.csv` (violations) and `{release}-warnings.csv` (warnings) for each release.

### Release Auto-Detection

When `--releases` is omitted, the script fetches the list of supported release branches from [`rhoai-release-data.yaml`](https://github.com/red-hat-data-services/rhods-devops-infra/blob/main/src/config/rhoai-release-data.yaml) in `rhods-devops-infra`. This is the single source of truth for which RHOAI versions are currently supported, including EA/in-development releases.

Some in-development/EA branches may not have a violations report CSV yet. The script reports failures per release -- this is expected and not a blocker.

### Handling User-Provided URLs

If the user provides a GitHub URL to a specific report (e.g. `https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.4/prod/release_day/conforma-violations-report.csv`), extract the release branch from the URL path (the segment after `/blob/` and before the next `/`) and pass it via `--releases`.

---

