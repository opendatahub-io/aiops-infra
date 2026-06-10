#!/usr/bin/env python3
"""Fetch conforma violation and warnings report CSVs from conforma-reporter per release.

Downloads violation and warnings CSVs from each release branch of the private
red-hat-data-services/conforma-reporter repository via raw download
(raw.githubusercontent.com), avoiding the GitHub Contents API entirely.
This handles multi-megabyte report files reliably without JSON/base64
overhead or API size limits.

Both violations and warnings are fetched by default. Warnings CSVs are
saved as ``{release}-warnings.csv`` alongside violation CSVs (``{release}.csv``).
Use ``--no-warnings`` to skip fetching warnings.

When --output-dir is omitted, automatically creates a timestamped directory
under .work/ (relative to this script's skill directory) and updates the
.work/latest symlink to point to it.

Part of the conforma-report-fetch skill. Consumed by conforma-analyze
(which passes --output-dir to keep .work/ writes local to its own skill).

Usage:
    # Auto-detect releases, auto-create .work/<timestamp>/:
    python3 scripts/fetch_csv_reports.py

    # Explicit releases, auto-create .work/<timestamp>/:
    python3 scripts/fetch_csv_reports.py --releases rhoai-3.5-ea.1

    # Explicit output directory:
    python3 scripts/fetch_csv_reports.py \\
      --releases rhoai-2.25,rhoai-3.4 \\
      --output-dir /tmp/conforma-reports

    # Skip warnings:
    python3 scripts/fetch_csv_reports.py --no-warnings

    # Use pre-downloaded CSVs instead of fetching:
    python3 scripts/fetch_csv_reports.py \\
      --local-dir /path/to/csvs
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = SKILL_DIR / ".work"


CONFORMA_REPORTER_REPO = "red-hat-data-services/conforma-reporter"
RAW_DOWNLOAD_BASE = "https://raw.githubusercontent.com"
CSV_FILENAME = "conforma-violations-report.csv"
WARNINGS_CSV_FILENAME = "conforma-warnings-report.csv"

CSV_PATHS = [
    f"prod/release_day/{CSV_FILENAME}",
    f"prod/future/build_type_latest/{CSV_FILENAME}",
    f"prod/future/build_type_nightly/{CSV_FILENAME}",
]

WARNINGS_CSV_PATHS = [
    f"prod/release_day/{WARNINGS_CSV_FILENAME}",
    f"prod/future/build_type_latest/{WARNINGS_CSV_FILENAME}",
    f"prod/future/build_type_nightly/{WARNINGS_CSV_FILENAME}",
]

_github_token_cache: str | None = None


def _get_github_token() -> str:
    """Get the GitHub token from gh CLI (cached for the process lifetime)."""
    global _github_token_cache
    if _github_token_cache is not None:
        return _github_token_cache
    result = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    _github_token_cache = result.stdout.strip() if result.returncode == 0 else ""
    return _github_token_cache


def _download_file_raw(csv_path: str, ref: str, output_file: Path) -> dict | None:
    """Download a file via raw.githubusercontent.com. Returns error dict or None on success.

    Always uses raw download — no Contents API, no JSON, no base64.
    Handles files of any size reliably.
    """
    token = _get_github_token()
    if not token:
        return {"error": "Failed to get GitHub token from 'gh auth token'"}

    url = f"{RAW_DOWNLOAD_BASE}/{CONFORMA_REPORTER_REPO}/{ref}/{csv_path}"
    result = subprocess.run(
        ["curl", "-fsSL", "-H", f"Authorization: token {token}", "-o", str(output_file), url],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        output_file.unlink(missing_ok=True)
        return {"error": result.stderr.strip()[:300]}

    if not output_file.exists() or output_file.stat().st_size == 0:
        output_file.unlink(missing_ok=True)
        return {"error": f"Downloaded file is empty or missing: {url}"}

    return None


def _fetch_last_commit_date(release: str, csv_path: str) -> str:
    """Get the ISO-8601 date of the last commit that touched the CSV file."""
    api_path = f"repos/{CONFORMA_REPORTER_REPO}/commits?path={csv_path}&sha={release}&per_page=1"
    result = subprocess.run(
        ["gh", "api", api_path, "--jq", ".[0].commit.committer.date"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return ""


def fetch_csv_for_release(release: str, output_dir: Path) -> dict:
    """Fetch the violations CSV for a single release branch via raw download.

    Tries CSV_PATHS in order (prod/release_day first, then fallbacks
    under prod/future/). Downloads directly from raw.githubusercontent.com
    to handle multi-megabyte report files without API size limits.
    """
    output_file = output_dir / f"{release}.csv"
    last_error = ""

    for csv_path in CSV_PATHS:
        err = _download_file_raw(csv_path, release, output_file)
        if err is None:
            created_at = _fetch_last_commit_date(release, csv_path)
            return {
                "release": release,
                "status": "fetched",
                "path": str(output_file),
                "size_bytes": output_file.stat().st_size,
                "source_path": csv_path,
                "created_at": created_at,
            }
        last_error = err["error"]

    return {
        "release": release,
        "status": "failed",
        "error": last_error,
        "path": None,
    }


def fetch_warnings_csv_for_release(release: str, output_dir: Path) -> dict:
    """Fetch the warnings CSV for a single release branch via raw download.

    Same fallback logic as fetch_csv_for_release but for the warnings report.
    Saves as ``{release}-warnings.csv``.
    """
    output_file = output_dir / f"{release}-warnings.csv"
    last_error = ""

    for csv_path in WARNINGS_CSV_PATHS:
        err = _download_file_raw(csv_path, release, output_file)
        if err is None:
            created_at = _fetch_last_commit_date(release, csv_path)
            return {
                "release": release,
                "status": "fetched",
                "path": str(output_file),
                "size_bytes": output_file.stat().st_size,
                "source_path": csv_path,
                "created_at": created_at,
            }
        last_error = err["error"]

    return {
        "release": release,
        "status": "failed",
        "error": last_error,
        "path": None,
    }


def copy_local_csvs(
    local_dir: Path,
    releases: list[str],
    output_dir: Path,
    *,
    include_warnings: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Copy pre-downloaded CSVs from a local directory.

    Returns (violation_results, warning_results).
    """
    results = []
    warning_results = []
    for release in releases:
        candidates = [
            local_dir / f"{release}.csv",
            local_dir / release / "conforma-violations-report.csv",
            local_dir / release / CSV_FILENAME,
        ]
        found = None
        for candidate in candidates:
            if candidate.is_file():
                found = candidate
                break

        if not found:
            results.append(
                {
                    "release": release,
                    "status": "failed",
                    "error": f"No CSV found for {release} in {local_dir}",
                    "path": None,
                }
            )
        else:
            output_file = output_dir / f"{release}.csv"
            shutil.copy2(found, output_file)
            results.append(
                {
                    "release": release,
                    "status": "copied",
                    "path": str(output_file),
                    "size_bytes": output_file.stat().st_size,
                }
            )

        if include_warnings:
            warn_candidates = [
                local_dir / f"{release}-warnings.csv",
                local_dir / release / "conforma-warnings-report.csv",
                local_dir / release / WARNINGS_CSV_FILENAME,
            ]
            warn_found = None
            for candidate in warn_candidates:
                if candidate.is_file():
                    warn_found = candidate
                    break

            if warn_found:
                output_file = output_dir / f"{release}-warnings.csv"
                shutil.copy2(warn_found, output_file)
                warning_results.append(
                    {
                        "release": release,
                        "status": "copied",
                        "path": str(output_file),
                        "size_bytes": output_file.stat().st_size,
                    }
                )

    return results, warning_results


RELEASE_DATA_REPO = "red-hat-data-services/rhods-devops-infra"
RELEASE_DATA_PATH = "src/config/rhoai-release-data.yaml"


def fetch_supported_releases() -> list[str]:
    """Fetch the list of supported release branches from rhods-devops-infra.

    Downloads rhoai-release-data.yaml via raw.githubusercontent.com and
    returns the `branch` field from each entry in the `supported` list.
    """
    import yaml

    token = _get_github_token()
    if not token:
        return []

    url = f"{RAW_DOWNLOAD_BASE}/{RELEASE_DATA_REPO}/main/{RELEASE_DATA_PATH}"
    result = subprocess.run(
        ["curl", "-fsSL", "-H", f"Authorization: token {token}", url],
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        return []

    try:
        data = yaml.safe_load(result.stdout.decode("utf-8"))
    except Exception:
        return []

    releases = []
    for entry in data.get("supported", []):
        if isinstance(entry, dict):
            for value in entry.values():
                if isinstance(value, dict) and "branch" in value:
                    releases.append(value["branch"])
                    break
            else:
                branch = entry.get("branch")
                if branch:
                    releases.append(branch)

    return releases


def _create_timestamped_output_dir() -> Path:
    """Create a timestamped run directory under .work/ and update the latest symlink."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = WORK_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    latest_link = WORK_DIR / "latest"
    # Atomic symlink update: create temp link then rename
    tmp_link = WORK_DIR / f".latest-{timestamp}"
    try:
        tmp_link.symlink_to(timestamp)
        tmp_link.rename(latest_link)
    except OSError:
        # Fallback: remove then create
        latest_link.unlink(missing_ok=True)
        latest_link.symlink_to(timestamp)

    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch conforma violation and warnings reports per release")
    parser.add_argument(
        "--releases",
        default=None,
        help="Comma-separated release branches (overrides auto-detection from rhods-devops-infra)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write CSV files to (default: auto-create .work/<timestamp>/)",
    )
    parser.add_argument(
        "--local-dir",
        default=None,
        help="Use pre-downloaded CSVs from this directory instead of fetching",
    )
    parser.add_argument(
        "--no-warnings",
        action="store_true",
        default=False,
        help="Skip fetching warnings CSVs (by default both violations and warnings are fetched)",
    )
    args = parser.parse_args()

    include_warnings = not args.no_warnings

    if args.releases:
        releases = [r.strip() for r in args.releases.split(",") if r.strip()]
    else:
        print(
            f"Fetching supported releases from {RELEASE_DATA_REPO}...",
            file=sys.stderr,
        )
        releases = fetch_supported_releases()
        if not releases:
            print(
                "Error: could not fetch supported releases from "
                f"{RELEASE_DATA_REPO}/{RELEASE_DATA_PATH}.\n"
                "Provide releases manually with --releases rhoai-2.25,rhoai-3.3,...",
                file=sys.stderr,
            )
            return 1
        print(
            f"  Found {len(releases)} supported releases: {', '.join(releases)}",
            file=sys.stderr,
        )

    if not releases:
        print("Error: no releases specified", file=sys.stderr)
        return 1

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = _create_timestamped_output_dir()
        print(f"Run directory: {output_dir}", file=sys.stderr)

    if args.local_dir:
        results, warning_results = copy_local_csvs(
            Path(args.local_dir), releases, output_dir, include_warnings=include_warnings
        )
    else:
        results = []
        warning_results = []
        for release in releases:
            print(f"Fetching {release} violations...", file=sys.stderr)
            result = fetch_csv_for_release(release, output_dir)
            results.append(result)
            if result["status"] == "fetched":
                source = result.get("source_path", "")
                print(
                    f"  OK: {result['size_bytes']} bytes -> {result['path']} (from {source})",
                    file=sys.stderr,
                )
            else:
                print(f"  FAIL: {result['error']}", file=sys.stderr)

            if include_warnings:
                print(f"Fetching {release} warnings...", file=sys.stderr)
                warn_result = fetch_warnings_csv_for_release(release, output_dir)
                warning_results.append(warn_result)
                if warn_result["status"] == "fetched":
                    source = warn_result.get("source_path", "")
                    print(
                        f"  OK: {warn_result['size_bytes']} bytes -> {warn_result['path']} (from {source})",
                        file=sys.stderr,
                    )
                else:
                    print(f"  WARN (warnings CSV): {warn_result['error']}", file=sys.stderr)

    succeeded = [r for r in results if r["status"] in ("fetched", "copied")]
    failed = [r for r in results if r["status"] == "failed"]
    warnings_succeeded = [r for r in warning_results if r["status"] in ("fetched", "copied")]
    warnings_failed = [r for r in warning_results if r["status"] == "failed"]

    output: dict = {
        "releases": {
            r["release"]: {
                "path": r["path"],
                "source_path": r.get("source_path", ""),
                "created_at": r.get("created_at", ""),
            }
            for r in succeeded
        },
        "total_fetched": len(succeeded),
        "total_failed": len(failed),
        "failures": [{"release": r["release"], "error": r["error"]} for r in failed],
    }

    if include_warnings:
        output["warnings"] = {
            "releases": {
                r["release"]: {
                    "path": r["path"],
                    "source_path": r.get("source_path", ""),
                    "created_at": r.get("created_at", ""),
                }
                for r in warnings_succeeded
            },
            "total_fetched": len(warnings_succeeded),
            "total_failed": len(warnings_failed),
            "failures": [{"release": r["release"], "error": r["error"]} for r in warnings_failed],
        }

    print(json.dumps(output, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
