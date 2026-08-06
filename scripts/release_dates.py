#!/usr/bin/env python3
"""Shared RHOAI release dates lookup.

Single source of truth for RHOAI release end-of-support (EOS) dates across
all conforma skills. All dates are fetched from rhai-release-data.yaml in
the rhods-devops-infra repository (canonical upstream source).

Public API
----------
get_eos_date(release)
    Raw support_end date string (YYYY-MM-DD) or None.

get_effective_until(release)
    Exception effectiveUntil timestamp (RFC3339) = EOS + 7 day buffer, or None.
    The +7 day buffer is only applied here; user-provided or Jira-sourced dates
    must be passed through as-is by callers.

resolve_effective_until_dates(versions)
    Batch lookup returning the same dict structure previously produced by
    preflight_check.resolve_effective_until_dates().

validate_effective_until_date(version, provided_date)
    Gate check: returns whether a provided effectiveUntil date matches the
    expected EOS + buffer for a given version. Used by consolidate_mrs.py.

CLI usage
---------
    python3 scripts/release_dates.py --release rhoai-3.4
    python3 scripts/release_dates.py --list
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    import yaml as _yaml
except ImportError:
    _yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EOS_BUFFER_DAYS = 7
PRODUCT_PAGES_URL = "https://productpages.redhat.com/"

_RELEASE_DATA_REPO = "red-hat-data-services/rhods-devops-infra"
_RELEASE_DATA_PATH = "src/config/rhai-release-data.yaml"
_RELEASE_DATA_FILE = "rhai-release-data.yaml"
_RELEASE_DATA_BRANCH = "main"
_RELEASE_DATA_URL = (
    f"https://github.com/{_RELEASE_DATA_REPO}/blob/{_RELEASE_DATA_BRANCH}/{_RELEASE_DATA_PATH}"
)
_RELEASE_DATA_LINK = f"[{_RELEASE_DATA_FILE}]({_RELEASE_DATA_URL})"


# ---------------------------------------------------------------------------
# Upcoming release date fetching
# ---------------------------------------------------------------------------

_release_data_cache: dict | None = None


def _release_to_base_version(release: str) -> str:
    """Extract the base version number from a release branch name.

    Examples: "rhoai-3.5" → "3.5", "rhoai-3.5-ea.2" → "3.5", "rhoai-2.25" → "2.25".
    """
    return re.sub(r"^rhoai-", "", release).split("-ea.")[0]


def _release_to_milestone_type(release: str) -> str:
    """Determine the milestone type to look for based on the release string.

    "rhoai-3.5" → "ga", "rhoai-3.5-ea.2" → "ea2", "rhoai-3.5-ea.1" → "ea1".
    """
    stripped = re.sub(r"^rhoai-", "", release)
    ea_match = re.search(r"-ea\.?(\d+)$", stripped)
    if ea_match:
        return f"ea{ea_match.group(1)}"
    return "ga"


def _fetch_release_data() -> dict | None:
    """Fetch and cache rhai-release-data.yaml from GitHub."""
    global _release_data_cache
    if _release_data_cache is not None:
        return _release_data_cache

    if _yaml is None:
        print("WARNING: PyYAML not available, cannot fetch release data", file=sys.stderr)
        return None

    try:
        import github_ops
    except ImportError:
        print("WARNING: github_ops not available, cannot fetch release data", file=sys.stderr)
        return None

    result = github_ops.get_file(_RELEASE_DATA_REPO, _RELEASE_DATA_PATH, ref=_RELEASE_DATA_BRANCH)
    if "error" in result:
        print(f"WARNING: Failed to fetch rhai-release-data.yaml: {result['error']}", file=sys.stderr)
        return None

    try:
        data = _yaml.safe_load(result["content"])
    except Exception:
        print("WARNING: Failed to parse rhai-release-data.yaml", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        return None

    _release_data_cache = data
    return data


def get_upcoming_release_date(release: str) -> Optional[str]:
    """Return the upcoming release date (YYYY-MM-DD) for a release.

    Fetches rhai-release-data.yaml from rhods-devops-infra and finds the
    milestone date matching the release type: GA date for GA queries
    (e.g. "rhoai-3.5"), EA2 date for EA2 queries (e.g. "rhoai-3.5-ea.2").

    Falls back to ``upcoming_release.date`` if no matching milestone exists.
    Returns None when the data cannot be fetched or no date is found.
    """
    data = _fetch_release_data()
    if data is None:
        return None

    base_version = _release_to_base_version(release)
    target_type = _release_to_milestone_type(release)

    for entry in data.get("supported", []):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("version", "")) != base_version:
            continue
        try:
            rhoai = entry["products"]["rhoai"]
        except (KeyError, TypeError):
            return None

        for milestone in rhoai.get("milestones", []):
            if not isinstance(milestone, dict):
                continue
            if milestone.get("type") == target_type:
                date_val = milestone.get("date")
                if date_val:
                    return str(date_val)

        return None

    return None


# ---------------------------------------------------------------------------
# EOS fetching from rhai-release-data.yaml
# ---------------------------------------------------------------------------


def _get_eos_from_remote(release: str) -> Optional[str]:
    """Try to extract end-of-support date from rhai-release-data.yaml.

    Looks for ``support.end_of_support`` on the matching version entry.
    Returns YYYY-MM-DD or None if the field does not exist.
    """
    data = _fetch_release_data()
    if data is None:
        return None

    base_version = _release_to_base_version(release)

    for entry in data.get("supported", []):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("version", "")) != base_version:
            continue
        support = entry.get("support", {})
        if isinstance(support, dict) and "end_of_support" in support:
            return str(support["end_of_support"])
        return None

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_version_label(release: str) -> str:
    """Convert a release branch name to a human-readable label.

    Examples: "rhoai-3.4" → "RHOAI 3.4", "rhoai-3.5-ea.2" → "RHOAI 3.5 EA2".
    """
    return release.replace("rhoai-", "RHOAI ").replace("-ea.", " EA")


def get_eos_date(release: str) -> Optional[str]:
    """Return the raw end-of-support date (YYYY-MM-DD) for a release.

    Fetches from rhai-release-data.yaml (canonical upstream source).
    Returns None when the release is not found.
    """
    return _get_eos_from_remote(release)


def get_eos_date_with_source(release: str) -> tuple[Optional[str], str]:
    """Return ``(date, source_link)`` for the end-of-support date.

    Fetches from rhai-release-data.yaml. The source_link is a markdown link
    to the source file.
    """
    date = _get_eos_from_remote(release)
    if date:
        return date, _RELEASE_DATA_LINK
    return None, ""


def get_code_freeze_date(release: str) -> Optional[str]:
    """Return the code freeze date (YYYY-MM-DD) for a release.

    Looks for ``{type}_code_freeze`` milestone in rhai-release-data.yaml
    (e.g. ``ga_code_freeze`` for GA, ``ea1_code_freeze`` for EA1).
    Falls back to generic ``code_freeze`` milestone for GA queries only
    (used by older releases like 3.3-3.4).

    Returns None when the data cannot be fetched, the version is not found,
    or the milestone is absent (e.g. code freeze date already past and
    removed from the YAML).
    """
    data = _fetch_release_data()
    if data is None:
        return None

    base_version = _release_to_base_version(release)
    target_type = _release_to_milestone_type(release)
    code_freeze_type = f"{target_type}_code_freeze"

    for entry in data.get("supported", []):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("version", "")) != base_version:
            continue
        try:
            rhoai = entry["products"]["rhoai"]
        except (KeyError, TypeError):
            return None

        for milestone in rhoai.get("milestones", []):
            if not isinstance(milestone, dict):
                continue
            if milestone.get("type") == code_freeze_type:
                date_val = milestone.get("date")
                if date_val:
                    return str(date_val)

        if target_type == "ga":
            for milestone in rhoai.get("milestones", []):
                if not isinstance(milestone, dict):
                    continue
                if milestone.get("type") == "code_freeze":
                    date_val = milestone.get("date")
                    if date_val:
                        return str(date_val)

        return None

    return None


def get_code_freeze_date_with_source(release: str) -> tuple[Optional[str], str]:
    """Return ``(date, source_link)`` for the code freeze date."""
    date = get_code_freeze_date(release)
    if date:
        return date, _RELEASE_DATA_LINK
    return None, ""


def get_upcoming_release_date_with_source(release: str) -> tuple[Optional[str], str]:
    """Return ``(date, source_link)`` for the upcoming release date.

    The source_link is a markdown link to the source file.
    """
    date = get_upcoming_release_date(release)
    if date:
        return date, _RELEASE_DATA_LINK
    return None, ""


def get_effective_until(release: str) -> Optional[str]:
    """Return the exception effectiveUntil timestamp (RFC3339) for a release.

    Applies a +7 day buffer to the EOS date.  The buffer is ONLY applied to
    dates sourced from this module — user-provided or Jira-sourced dates must
    be used as-is by callers.

    Returns None when the release is not found.
    """
    raw = get_eos_date(release)
    if raw is None:
        return None
    dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    dt += timedelta(days=_EOS_BUFFER_DAYS)
    return dt.strftime("%Y-%m-%dT00:00:00Z")


def resolve_effective_until_dates(rhoai_versions: list[str]) -> dict[str, dict]:
    """Batch-resolve effectiveUntil dates for a list of release strings.

    Drop-in replacement for the former preflight_check.resolve_effective_until_dates().
    """
    results: dict[str, dict] = {}
    for ver in rhoai_versions:
        effective_until = get_effective_until(ver)
        if effective_until:
            results[ver] = {
                "effectiveUntil": effective_until,
                "source": "rhai-release-data",
                "note": f"End-of-support date + {_EOS_BUFFER_DAYS} day buffer",
            }
        else:
            results[ver] = {
                "effectiveUntil": None,
                "source": "unknown",
                "note": f"No EOS date configured for {ver}. User must provide.",
            }
    return results


def validate_effective_until_date(version: str, provided_date: str) -> dict:
    """Validate that a provided effectiveUntil date matches the expected EOS + buffer.

    Used by consolidate_mrs.py when consolidating per-version exception MRs.

    Args:
        version:       RHOAI release string, e.g. "rhoai-3.4".
        provided_date: RFC3339 or YYYY-MM-DD date string from the existing MR.

    Returns a dict with:
        valid:    bool   — True if dates match (or no expectation exists).
        provided: str    — YYYY-MM-DD portion of the input date.
        expected: str | None — YYYY-MM-DD of EOS + buffer, or None if unknown.
        detail:   str    — Human-readable explanation.
    """
    provided_ymd = provided_date[:10] if provided_date else ""
    expected_full = get_effective_until(version)

    if expected_full is None:
        return {
            "valid": True,
            "provided": provided_ymd,
            "expected": None,
            "detail": f"No EOS date configured for {version}; cannot validate.",
        }

    expected_ymd = expected_full[:10]
    valid = provided_ymd == expected_ymd
    detail = (
        f"Date matches expected EOS + {_EOS_BUFFER_DAYS}d."
        if valid
        else (
            f"Expected {expected_ymd} (EOS + {_EOS_BUFFER_DAYS}d), "
            f"got {provided_ymd}."
        )
    )
    return {
        "valid": valid,
        "provided": provided_ymd,
        "expected": expected_ymd,
        "detail": detail,
    }


def list_all() -> list[dict]:
    """Return all known releases with their EOS and effectiveUntil dates."""
    data = _fetch_release_data()
    if data is None:
        return []
    rows = []
    for entry in data.get("supported", []):
        if not isinstance(entry, dict):
            continue
        version = str(entry.get("version", ""))
        if not version:
            continue
        release = f"rhoai-{version}"
        eos = _get_eos_from_remote(release)
        rows.append({
            "release": release,
            "end_of_support": eos,
            "effective_until": get_effective_until(release),
            "upcoming_release_date": get_upcoming_release_date(release),
            "source": "rhai-release-data",
        })
    return sorted(rows, key=lambda r: r["release"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="RHOAI release dates lookup")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--release", help="Release to look up (e.g. rhoai-3.4)")
    group.add_argument("--list", action="store_true", help="List all known releases")
    args = parser.parse_args()

    if args.list:
        json.dump(list_all(), sys.stdout, indent=2)
        print()
        return 0

    eos = get_eos_date(args.release)
    if eos is None:
        print(json.dumps({
            "release": args.release,
            "end_of_support": None,
            "effective_until": None,
            "source": "unknown",
            "note": f"No EOS date configured for {args.release}.",
        }, indent=2))
        return 1

    print(json.dumps({
        "release": args.release,
        "end_of_support": eos,
        "effective_until": get_effective_until(args.release),
        "upcoming_release_date": get_upcoming_release_date(args.release),
        "source": "rhai-release-data",
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
