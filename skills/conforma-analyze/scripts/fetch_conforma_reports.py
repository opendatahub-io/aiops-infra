#!/usr/bin/env python3
"""Fetch conforma violation report CSVs from conforma-reporter per release.

Downloads the CSV from each release branch of the private
red-hat-data-services/conforma-reporter repository using the gh CLI.

Usage:
    python3 scripts/fetch_conforma_reports.py \\
      --releases rhoai-2.25,rhoai-3.3,rhoai-3.4 \\
      --output-dir /tmp/conforma-reports

    # Use pre-downloaded CSVs instead of fetching:
    python3 scripts/fetch_conforma_reports.py \\
      --local-dir /path/to/csvs \\
      --output-dir /tmp/conforma-reports
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path


CONFORMA_REPORTER_REPO = "red-hat-data-services/conforma-reporter"
CSV_FILENAME = "conforma-violations-report.csv"

CSV_PATHS = [
    f"prod/release_day/{CSV_FILENAME}",
    f"prod/future/build_type_latest/{CSV_FILENAME}",
    f"prod/future/build_type_nightly/{CSV_FILENAME}",
]


def _download_file(api_path: str, output_file: Path) -> dict | None:
    """Download a file via the Contents API. Returns error dict or None on success."""
    result = subprocess.run(
        ["gh", "api", api_path, "-H", "Accept: application/vnd.github.v3+json"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        return {"error": result.stderr.strip()[:300]}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"Failed to parse API response: {exc}"}

    encoding = data.get("encoding", "")

    if encoding == "base64":
        try:
            csv_bytes = base64.b64decode(data.get("content", ""))
            output_file.write_bytes(csv_bytes)
        except Exception as exc:
            return {"error": f"Failed to decode base64 content: {exc}"}
    else:
        download_url = data.get("download_url")
        if not download_url:
            return {"error": "File too large for base64 and no download_url available"}
        dl_result = subprocess.run(
            ["gh", "api", download_url, "--method", "GET"],
            capture_output=True,
            timeout=120,
        )
        if dl_result.returncode != 0:
            return {
                "error": f"Download failed: {dl_result.stderr.decode(errors='replace').strip()[:200]}"
            }
        output_file.write_bytes(dl_result.stdout)

    return None


def fetch_csv_for_release(release: str, output_dir: Path) -> dict:
    """Fetch the violations CSV for a single release branch via gh API.

    Tries CSV_PATHS in order (prod/release_day first, then fallbacks
    under prod/future/). Uses the Contents API with ref as a query
    parameter. When the file is too large for base64, falls back to the
    raw download URL.
    """
    output_file = output_dir / f"{release}.csv"
    last_error = ""

    for csv_path in CSV_PATHS:
        api_path = (
            f"repos/{CONFORMA_REPORTER_REPO}/contents/{csv_path}?ref={release}"
        )
        err = _download_file(api_path, output_file)
        if err is None:
            return {
                "release": release,
                "status": "fetched",
                "path": str(output_file),
                "size_bytes": output_file.stat().st_size,
                "source_path": csv_path,
            }
        last_error = err["error"]

    return {
        "release": release,
        "status": "failed",
        "error": last_error,
        "path": None,
    }


def copy_local_csvs(local_dir: Path, releases: list[str], output_dir: Path) -> list[dict]:
    """Copy pre-downloaded CSVs from a local directory."""
    results = []
    for release in releases:
        candidates = [
            local_dir / f"{release}.csv",
            local_dir / release / "conforma-violations-report.csv",
            local_dir / release / CSV_PATH.split("/")[-1],
        ]
        found = None
        for candidate in candidates:
            if candidate.is_file():
                found = candidate
                break

        if not found:
            results.append({
                "release": release,
                "status": "failed",
                "error": f"No CSV found for {release} in {local_dir}",
                "path": None,
            })
            continue

        output_file = output_dir / f"{release}.csv"
        shutil.copy2(found, output_file)
        results.append({
            "release": release,
            "status": "copied",
            "path": str(output_file),
            "size_bytes": output_file.stat().st_size,
        })

    return results


RELEASE_DATA_REPO = "red-hat-data-services/rhods-devops-infra"
RELEASE_DATA_PATH = "src/config/rhoai-release-data.yaml"


def fetch_supported_releases() -> list[str]:
    """Fetch the list of supported release branches from rhods-devops-infra.

    Reads rhoai-release-data.yaml and returns the `branch` field from
    each entry in the `supported` list.
    """
    import yaml

    api_path = f"repos/{RELEASE_DATA_REPO}/contents/{RELEASE_DATA_PATH}?ref=main"
    result = subprocess.run(
        ["gh", "api", api_path, "--jq", ".download_url"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return []

    download_url = result.stdout.strip()
    if not download_url:
        return []

    dl_result = subprocess.run(
        ["gh", "api", download_url, "--method", "GET"],
        capture_output=True,
        timeout=30,
    )
    if dl_result.returncode != 0:
        return []

    try:
        data = yaml.safe_load(dl_result.stdout.decode("utf-8"))
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch conforma violation reports per release"
    )
    parser.add_argument(
        "--releases",
        default=None,
        help="Comma-separated release branches (overrides auto-detection from rhods-devops-infra)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write CSV files to",
    )
    parser.add_argument(
        "--local-dir",
        default=None,
        help="Use pre-downloaded CSVs from this directory instead of fetching",
    )
    args = parser.parse_args()

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

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.local_dir:
        results = copy_local_csvs(Path(args.local_dir), releases, output_dir)
    else:
        results = []
        for release in releases:
            print(f"Fetching {release}...", file=sys.stderr)
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

    succeeded = [r for r in results if r["status"] in ("fetched", "copied")]
    failed = [r for r in results if r["status"] == "failed"]

    output = {
        "releases": {
            r["release"]: {"path": r["path"], "source_path": r.get("source_path", "")}
            for r in succeeded
        },
        "total_fetched": len(succeeded),
        "total_failed": len(failed),
        "failures": [{"release": r["release"], "error": r["error"]} for r in failed],
    }

    print(json.dumps(output, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
