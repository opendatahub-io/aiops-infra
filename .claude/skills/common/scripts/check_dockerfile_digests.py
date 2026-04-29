#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Check that every FROM instruction in a Dockerfile pins its image with a SHA digest.

Tags alone (e.g. :latest, :22.04) are not accepted.
Valid forms:
  FROM registry.example.com/image@sha256:<hex>
  FROM registry.example.com/image:tag@sha256:<hex>   # tag + digest (tag is informational)
Skipped:
  FROM scratch
  FROM $ARG_NAME  (ARG-substituted references cannot be checked statically)

Exit 0  — all FROM instructions are pinned with @sha256:
Exit 1  — one or more violations found (details on stderr)
Exit 2  — Dockerfile could not be fetched/read
"""

import argparse
import re
import sys
import urllib.request


def fetch(source: str) -> str:
    try:
        if source.startswith("http://") or source.startswith("https://"):
            with urllib.request.urlopen(source) as resp:
                return resp.read().decode()
        else:
            with open(source) as f:
                return f.read()
    except Exception as exc:
        print(f"ERROR: Could not read Dockerfile from {source!r}: {exc}", file=sys.stderr)
        sys.exit(2)


def parse_froms(content: str) -> list[tuple[int, str]]:
    """Return [(lineno, image_ref), ...] for every FROM instruction."""
    results = []
    for i, line in enumerate(content.splitlines(), 1):
        m = re.match(r"^\s*FROM\s+(\S+)", line, re.IGNORECASE)
        if m:
            results.append((i, m.group(1)))
    return results


def main() -> None:
    p = argparse.ArgumentParser(
        description="Verify all Dockerfile FROM instructions use @sha256 digests"
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--dockerfile-url", metavar="URL", help="HTTP(S) URL of the Dockerfile")
    src.add_argument("--dockerfile-path", metavar="PATH", help="Local filesystem path")
    args = p.parse_args()

    source = args.dockerfile_url or args.dockerfile_path
    content = fetch(source)
    froms = parse_froms(content)

    if not froms:
        print("WARNING: No FROM instructions found in Dockerfile — nothing to check.")
        sys.exit(0)

    violations = []
    for lineno, ref in froms:
        # Skip build-time ARG substitutions and scratch
        if ref.lower() == "scratch" or ref.startswith("$"):
            continue
        if "@sha256:" not in ref:
            violations.append((lineno, ref))

    if violations:
        print(
            f"FAIL: {len(violations)} FROM instruction(s) do not pin images with SHA digests:",
            file=sys.stderr,
        )
        for lineno, ref in violations:
            print(f"  Line {lineno}: FROM {ref}", file=sys.stderr)
        print(
            "\nAll base and builder images must use @sha256 digests, not tags alone.\n"
            "Correct format:\n"
            "  FROM registry.example.com/image@sha256:<64-hex-chars>\n"
            "  FROM registry.example.com/image:tag@sha256:<64-hex-chars>  # tag optional",
            file=sys.stderr,
        )
        sys.exit(1)

    checked = len(froms) - sum(
        1 for _, ref in froms if ref.lower() == "scratch" or ref.startswith("$")
    )
    print(f"OK: All {checked} checkable FROM instruction(s) use @sha256 digests.")


if __name__ == "__main__":
    main()
