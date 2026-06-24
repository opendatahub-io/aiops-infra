#!/usr/bin/env python3
"""Shared RHOAI release dates lookup.

Single source of truth for RHOAI release end-of-support (EOS) dates across
all conforma skills.

Static dates are loaded from scripts/release_dates.yaml.
Future: plug in a dynamic backend via _fetch_dynamic() — e.g. the Red Hat
Product Lifecycle API — without changing any callers.

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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    import yaml as _yaml
except ImportError:
    _yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_YAML_PATH = Path(__file__).resolve().parent / "release_dates.yaml"
_EOS_BUFFER_DAYS = 7


# ---------------------------------------------------------------------------
# Static data source
# ---------------------------------------------------------------------------


def _load_static() -> dict[str, str]:
    """Load release → support_end mapping from YAML. Returns {} on any failure."""
    if _yaml is None:
        return {}
    try:
        with open(_YAML_PATH) as fh:
            data = _yaml.safe_load(fh) or {}
        releases = data.get("releases", {})
        return {
            k: str(v["support_end"])
            for k, v in releases.items()
            if isinstance(v, dict) and "support_end" in v
        }
    except Exception:
        return {}


_STATIC_DATES: dict[str, str] = _load_static()


# ---------------------------------------------------------------------------
# Dynamic fetching — stub for future implementation
# ---------------------------------------------------------------------------


def _fetch_dynamic(release: str) -> Optional[str]:
    """Fetch EOS date from a live source. Not yet implemented.

    Future candidates:
    - Red Hat Product Lifecycle API
    - A shared config repo (e.g. rhods-devops-infra/rhoai-release-data.yaml)

    Returns YYYY-MM-DD or None.
    """
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_eos_date(release: str) -> Optional[str]:
    """Return the raw end-of-support date (YYYY-MM-DD) for a release.

    Checks the static YAML first; falls back to dynamic fetching (stub).
    Returns None when the release is not found in either source.
    """
    return _STATIC_DATES.get(release) or _fetch_dynamic(release)


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
                "source": "release_dates_yaml",
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
    rows = []
    for release, eos in sorted(_STATIC_DATES.items()):
        rows.append({
            "release": release,
            "end_of_support": eos,
            "effective_until": get_effective_until(release),
            "source": "static",
        })
    return rows


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
        "source": "static",
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
