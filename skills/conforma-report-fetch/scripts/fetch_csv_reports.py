#!/usr/bin/env python3
"""fetch_csv_reports — Fetch conforma violation and warnings report CSVs from conforma-reporter per release.

PUBLIC API:
    fetch_csv_for_release(release, output_dir, environment) -> dict  [line 228]
    fetch_warnings_csv_for_release(release, output_dir, environment) -> dict  [line 262]
    copy_local_csvs(local_dir, releases, output_dir) -> tuple[list[dict], list[dict]]  [line 294]
    fetch_supported_releases() -> list[str]  [line 371]
    main() -> int  [line 436]

INTERNAL SECTIONS:
    Main: _get_github_token, _download_file_raw, _fetch_last_commit_info, _fetch_last_commit_info_gh, _create_timestamped_output_dir

DEPENDENCIES: argparse, conforma_constants, conforma_context_ops, datetime, json, os, pathlib, requests, shutil, subprocess

"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _setup_env  # noqa: F401, E402

import conforma_context_ops  # noqa: E402
import requests  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = _setup_env.REPO_ROOT
WORK_DIR = SKILL_DIR / ".work"


from conforma_constants import (  # noqa: E402
    CONFORMA_REPORTER_REPO,
    CSV_FILENAME,
    RAW_DOWNLOAD_BASE,
    WARNINGS_CSV_FILENAME,
    csv_paths_for_environment,
    warnings_csv_paths_for_environment,
)

_github_token_cache: str | None = None


def _get_github_token() -> str:
    """Get GitHub token from env vars or gh CLI (cached for the process lifetime).

    Resolution order: GITHUB_TOKEN, GH_TOKEN, then `gh auth token`.
    """
    global _github_token_cache
    if _github_token_cache is not None:
        return _github_token_cache

    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            _github_token_cache = val
            return _github_token_cache

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        _github_token_cache = result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _github_token_cache = ""
    return _github_token_cache


def _download_file_raw(csv_path: str, ref: str, output_file: Path) -> dict | None:
    """Download a file via raw.githubusercontent.com. Returns error dict or None on success.

    Uses requests for streaming download — no curl dependency.
    Handles files of any size reliably.
    """
    token = _get_github_token()
    if not token:
        return {"error": "No GitHub token found (set GITHUB_TOKEN in ~/.conforma/.env)"}

    url = f"{RAW_DOWNLOAD_BASE}/{CONFORMA_REPORTER_REPO}/{ref}/{csv_path}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"token {token}"},
            timeout=120,
            stream=True,
        )
        if resp.status_code == 404:
            return {"error": f"File not found: {csv_path} on {ref}"}
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code} downloading {url}"}

        with open(output_file, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
    except requests.RequestException as exc:
        output_file.unlink(missing_ok=True)
        return {"error": str(exc)[:300]}

    if not output_file.exists() or output_file.stat().st_size == 0:
        output_file.unlink(missing_ok=True)
        return {"error": f"Downloaded file is empty or missing: {url}"}

    return None


def _fetch_last_commit_info(release: str, csv_path: str) -> dict[str, str]:
    """Get the date and SHA of the last commit that touched the CSV file.

    Tries the GitHub REST API via ``requests`` first, then falls back to
    ``gh api`` CLI (which handles proxy/auth through its own config).

    Returns ``{"date": "<ISO-8601>", "sha": "<hex>"}`` on success,
    or ``{"date": "", "sha": ""}`` on any failure (with a warning on stderr).
    """
    empty: dict[str, str] = {"date": "", "sha": ""}
    token = _get_github_token()

    # --- Primary: requests ---
    if token:
        url = (
            f"https://api.github.com/repos/{CONFORMA_REPORTER_REPO}/commits"
            f"?path={csv_path}&sha={release}&per_page=1"
        )
        try:
            resp = requests.get(
                url,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                commits = resp.json()
                if commits:
                    return {
                        "date": commits[0].get("commit", {}).get("committer", {}).get("date", ""),
                        "sha": commits[0].get("sha", ""),
                    }
                print(f"  WARN: No commits found for {csv_path} on {release}", file=sys.stderr)
            else:
                print(
                    f"  WARN: GitHub commits API returned {resp.status_code} for {csv_path} on {release}",
                    file=sys.stderr,
                )
        except (requests.RequestException, KeyError, IndexError) as exc:
            print(
                f"  WARN: Failed to fetch commit metadata for {csv_path} on {release}: {exc}",
                file=sys.stderr,
            )

    # --- Fallback: gh api (handles proxy/auth via its own config) ---
    result = _fetch_last_commit_info_gh(release, csv_path)
    if result["date"]:
        return result
    return empty


def _fetch_last_commit_info_gh(release: str, csv_path: str) -> dict[str, str]:
    """Get commit metadata via ``gh api`` CLI as a fallback.

    The ``gh`` CLI uses its own auth token store and proxy handling,
    which may succeed when ``requests`` fails (e.g. corporate proxy
    blocking ``api.github.com`` but ``gh`` routing differently).
    """
    empty: dict[str, str] = {"date": "", "sha": ""}
    gh = shutil.which("gh")
    if not gh:
        return empty
    try:
        proc = subprocess.run(
            [
                gh, "api",
                f"/repos/{CONFORMA_REPORTER_REPO}/commits",
                "-f", f"path={csv_path}",
                "-f", f"sha={release}",
                "-f", "per_page=1",
                "--jq", ".[0] | .commit.committer.date + \"\\n\" + .sha",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            parts = proc.stdout.strip().split("\n", 1)
            if len(parts) == 2:
                return {"date": parts[0], "sha": parts[1]}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        print(f"  WARN: gh api fallback also failed: {exc}", file=sys.stderr)
    return empty


def fetch_csv_for_release(release: str, output_dir: Path, environment: str) -> dict:
    """Fetch the violations CSV for a single release branch via raw download.

    Tries CSV paths in order (build_type_latest first, then
    build_type_nightly) for the given environment. Downloads directly from
    raw.githubusercontent.com to handle multi-megabyte report files
    without API size limits.
    """
    output_file = output_dir / f"{release}.csv"
    last_error = ""

    for csv_path in csv_paths_for_environment(environment):
        err = _download_file_raw(csv_path, release, output_file)
        if err is None:
            commit_info = _fetch_last_commit_info(release, csv_path)
            return {
                "release": release,
                "status": "fetched",
                "path": str(output_file),
                "size_bytes": output_file.stat().st_size,
                "source_path": csv_path,
                "created_at": commit_info["date"],
                "source_sha": commit_info["sha"],
            }
        last_error = err["error"]

    return {
        "release": release,
        "status": "failed",
        "error": last_error,
        "path": None,
    }


def fetch_warnings_csv_for_release(release: str, output_dir: Path, environment: str) -> dict:
    """Fetch the warnings CSV for a single release branch via raw download.

    Same fallback logic as fetch_csv_for_release but for the warnings report.
    Saves as ``{release}-warnings.csv``.
    """
    output_file = output_dir / f"{release}-warnings.csv"
    last_error = ""

    for csv_path in warnings_csv_paths_for_environment(environment):
        err = _download_file_raw(csv_path, release, output_file)
        if err is None:
            commit_info = _fetch_last_commit_info(release, csv_path)
            return {
                "release": release,
                "status": "fetched",
                "path": str(output_file),
                "size_bytes": output_file.stat().st_size,
                "source_path": csv_path,
                "created_at": commit_info["date"],
                "source_sha": commit_info["sha"],
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
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"token {token}"},
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        content = resp.text
    except requests.RequestException:
        return []

    try:
        data = yaml.safe_load(content)
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
    """Create a timestamped run directory under ~/.conforma/ and update the latest symlink."""
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
        "--run-dir",
        default=None,
        help="Path to run directory with context.yaml. Auto-discovered via .conforma-active if omitted.",
    )
    parser.add_argument(
        "--releases",
        default=None,
        help="Comma-separated release branches to fetch (required unless --all is used)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        dest="fetch_all",
        help="Fetch all supported releases (auto-detected from rhods-devops-infra). "
        "Without --releases or --all, the script refuses to run to prevent "
        "accidentally fetching all releases when a specific one was intended.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write CSV files to (default: auto-create ~/.conforma/<timestamp>/)",
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
    parser.add_argument(
        "--environment",
        choices=["prod", "stage"],
        default=None,
        help="Target environment (prod or stage). Auto-discovered from context if not specified.",
    )
    parser.add_argument(
        "--metadata-file",
        default=None,
        help="Write JSON metadata to this file instead of stdout (avoids stdout/stderr mixing issues)",
    )
    args = parser.parse_args()

    context = None
    run_dir = None
    try:
        run_dir = conforma_context_ops.discover_run_dir(args.run_dir)
        context = conforma_context_ops.load(run_dir)
    except FileNotFoundError:
        if args.run_dir:
            raise

    environment = conforma_context_ops.resolve_arg(args, "environment", context, "environment")
    include_warnings = not args.no_warnings

    if args.releases:
        releases = [r.strip() for r in args.releases.split(",") if r.strip()]
    elif args.fetch_all:
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
    elif context and context.get("application", {}).get("release"):
        releases = [context["application"]["release"]]
        print(f"Using release from context: {releases[0]}", file=sys.stderr)
    else:
        print(
            "Error: specify --releases <release1,release2,...> or --all.\n"
            "Refusing to auto-detect releases without explicit --all flag to "
            "prevent accidentally fetching all releases when a specific one "
            "was intended.\n"
            "Examples:\n"
            "  --releases rhoai-3.5-ea.1          # fetch one release\n"
            "  --releases rhoai-3.4,rhoai-3.5     # fetch specific releases\n"
            "  --all                               # fetch all supported releases",
            file=sys.stderr,
        )
        return 1

    if not releases:
        print("Error: no releases specified", file=sys.stderr)
        return 1

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    elif run_dir:
        output_dir = run_dir
        print(f"Writing to run directory: {output_dir}", file=sys.stderr)
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
            result = fetch_csv_for_release(release, output_dir, environment=environment)
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
                warn_result = fetch_warnings_csv_for_release(release, output_dir, environment=environment)
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
                "source_sha": r.get("source_sha", ""),
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
                    "source_sha": r.get("source_sha", ""),
                }
                for r in warnings_succeeded
            },
            "total_fetched": len(warnings_succeeded),
            "total_failed": len(warnings_failed),
            "failures": [{"release": r["release"], "error": r["error"]} for r in warnings_failed],
        }

    if run_dir:
        step_outputs: dict = {}
        if succeeded:
            step_outputs["csv_files"] = [Path(r["path"]).name for r in succeeded]
            step_outputs["source_sha"] = succeeded[0].get("source_sha", "")
            step_outputs["source_path"] = succeeded[0].get("source_path", "")
            step_outputs["source_created_at"] = succeeded[0].get("created_at", "")
        if warnings_succeeded:
            step_outputs["warnings_csv_files"] = [Path(r["path"]).name for r in warnings_succeeded]
        step_status = "completed" if not failed else "failed"
        conforma_context_ops.update_step(run_dir, "fetch", step_status, **step_outputs)

    json_output = json.dumps(output, indent=2)
    if args.metadata_file:
        Path(args.metadata_file).write_text(json_output + "\n", encoding="utf-8")
        print(f"Metadata written to {args.metadata_file}", file=sys.stderr)
    else:
        print(json_output)

    if run_dir and not args.metadata_file:
        rundir_metadata = Path(run_dir) / "fetch-metadata.json"
        rundir_metadata.write_text(json_output + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
