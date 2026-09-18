"""Shared Conforma release and component identity primitives.

The functions in this module return JSON-serializable dictionaries so callers
can retain both canonical comparison data and the original evidence text.
"""

from __future__ import annotations

import argparse
import json
import re

_RELEASE_RE = re.compile(
    r"^(?:(?P<family>(?!v(?=\d))[a-z][a-z0-9]*)[\s._-]*)?"
    r"v?(?P<major>\d+)[\s._-](?P<minor>\d+)"
    r"(?:[\s._-]*(?P<stage>ea|ga|rc)[\s._-]*(?P<stage_number>\d+))?$",
    re.IGNORECASE,
)
_STAGE_FRAGMENT_RE = re.compile(r"^(?P<stage>ea|ga|rc)[\s._-]*(?P<stage_number>\d+)$", re.IGNORECASE)
_COMPONENT_RE = re.compile(
    r"^(?P<base>.+?)[-_]v(?P<major>\d+)[-_.](?P<minor>\d+)"
    r"(?:[-_.](?P<stage>ea|ga|rc)[-_.]?(?P<stage_number>\d+))?$",
    re.IGNORECASE,
)


def _canonical_text(parsed: dict) -> str:
    value = f"{parsed['major']}.{parsed['minor']}"
    if parsed.get("stage"):
        value += f"-{parsed['stage']}.{parsed['stage_number']}"
    if parsed.get("product_family"):
        value = f"{parsed['product_family']}-{value}"
    return value


def parse_release(value: str, context: str = "") -> dict | None:
    """Parse a release spelling into canonical fields and retain evidence.

    A stage fragment such as ``ea 2`` is accepted only when *context* supplies
    the product family and major/minor release. This prevents a bare fragment
    from becoming a false positive.
    """
    original = (value or "").strip()
    if not original:
        return None
    match = _RELEASE_RE.fullmatch(original.lower())
    if not match:
        fragment = _STAGE_FRAGMENT_RE.fullmatch(original.lower())
        context_parsed = parse_release(context) if fragment and context != value else None
        if not fragment or not context_parsed or context_parsed.get("stage"):
            return None
        parsed = dict(context_parsed)
        parsed["stage"] = fragment.group("stage").lower()
        parsed["stage_number"] = int(fragment.group("stage_number"))
        parsed["original"] = original
        parsed["context"] = context
        parsed["canonical"] = _canonical_text(parsed)
        return parsed

    parsed = {
        "original": original,
        "product_family": match.group("family").lower() if match.group("family") else None,
        "major": int(match.group("major")),
        "minor": int(match.group("minor")),
        "stage": match.group("stage").lower() if match.group("stage") else None,
        "stage_number": int(match.group("stage_number")) if match.group("stage_number") else None,
    }
    parsed["canonical"] = _canonical_text(parsed)
    return parsed


def normalize_release(value: str, context: str = "") -> str | None:
    """Return the canonical release spelling, or ``None`` when unparseable."""
    parsed = parse_release(value, context=context)
    return parsed["canonical"] if parsed else None


def release_matches(candidate: str, analyzed: str) -> bool:
    """Compare equivalent release forms without substring matching."""
    candidate_parsed = parse_release(candidate)
    analyzed_parsed = parse_release(analyzed)
    if not candidate_parsed or not analyzed_parsed:
        return False
    if (
        candidate_parsed["product_family"]
        and analyzed_parsed["product_family"]
        and candidate_parsed["product_family"] != analyzed_parsed["product_family"]
    ):
        return False
    if (candidate_parsed["major"], candidate_parsed["minor"]) != (
        analyzed_parsed["major"],
        analyzed_parsed["minor"],
    ):
        return False
    # A product version without a stage is a release-level signal and may
    # match a staged build of that same major/minor release.
    if candidate_parsed["stage"] and analyzed_parsed["stage"]:
        return (candidate_parsed["stage"], candidate_parsed["stage_number"]) == (
            analyzed_parsed["stage"],
            analyzed_parsed["stage_number"],
        )
    return True


def parse_component(value: str) -> dict:
    """Return full component text, release-independent identity, and suffix release."""
    original = (value or "").strip()
    match = _COMPONENT_RE.fullmatch(original)
    if not match:
        return {
            "original": original,
            "full_name": original,
            "stem": original,
            "identity": original.lower(),
            "release": None,
        }
    base = match.group("base")
    release_text = f"v{match.group('major')}-{match.group('minor')}"
    if match.group("stage"):
        release_text += f"-{match.group('stage')}-{match.group('stage_number')}"
    release = parse_release(release_text)
    return {"original": original, "full_name": original, "stem": base, "identity": base.lower(), "release": release}


def component_stem(value: str) -> str:
    """Return the release-independent component name, preserving its spelling."""
    return parse_component(value)["stem"]


def component_identity(value: str) -> str:
    """Return a stable lower-case component identity without a release suffix."""
    return parse_component(value)["identity"]


def component_matches(candidate: str, requested: str) -> bool:
    """Compare component identities and, when both are versioned, releases."""
    candidate_parsed = parse_component(candidate)
    requested_parsed = parse_component(requested)
    if candidate_parsed["identity"] != requested_parsed["identity"]:
        return False
    if candidate_parsed["release"] and requested_parsed["release"]:
        return release_matches(candidate_parsed["release"]["canonical"], requested_parsed["release"]["canonical"])
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Conforma release and component normalization primitives")
    sub = parser.add_subparsers(dest="command")
    release_parser = sub.add_parser("parse-release")
    release_parser.add_argument("--value", required=True)
    release_parser.add_argument("--context", default="")
    component_parser = sub.add_parser("parse-component")
    component_parser.add_argument("--value", required=True)
    args = parser.parse_args()
    if args.command == "parse-release":
        result = parse_release(args.value, args.context)
    elif args.command == "parse-component":
        result = parse_component(args.value)
    else:
        parser.print_help()
        raise SystemExit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
