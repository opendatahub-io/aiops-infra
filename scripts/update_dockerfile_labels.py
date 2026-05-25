#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Add or fix mandatory RHOAI OCI labels in a Dockerfile.

Usage:
  uv run --script update_dockerfile_labels.py <dockerfile-path> \
    --name        "rhoai/<component>-rhel9" \
    --component   "<component>-rhel9" \
    --default     "<component>"

Modifies the Dockerfile in place. Appends a consolidated LABEL block with all
7 mandatory labels at the end of the file (after last FROM). Later LABEL
instructions in a Dockerfile override earlier ones, so this is safe even when
some labels already exist with the correct value.

Exit 0: all labels are correct (file unchanged) or were successfully added.
Exit 1: unrecoverable error.
"""
import argparse
import re
import sys
from pathlib import Path

MANDATORY_KEYS = [
    "name",
    "com.redhat.component",
    "summary",
    "description",
    "maintainer",
    "io.k8s.display-name",
    "io.k8s.description",
]


def _parse_labels(content: str) -> dict:
    """Extract current label key→value pairs from all LABEL instructions."""
    labels = {}
    for m in re.finditer(r'([A-Za-z0-9._-]+)="([^"]*)"', content):
        labels[m.group(1)] = m.group(2)
    return labels


def main():
    parser = argparse.ArgumentParser(description="Update mandatory RHOAI Dockerfile labels")
    parser.add_argument("dockerfile")
    parser.add_argument("--name",      required=True, help="Expected value for 'name' label")
    parser.add_argument("--component", required=True, help="Expected value for 'com.redhat.component'")
    parser.add_argument("--default",   required=True, help="Expected value for summary/description/etc.")
    args = parser.parse_args()

    path = Path(args.dockerfile)
    if not path.exists():
        print(f"ERROR: Dockerfile not found: {path}", file=sys.stderr)
        sys.exit(1)

    expected = {
        "name":                 args.name,
        "com.redhat.component": args.component,
        "summary":              args.default,
        "description":          args.default,
        "maintainer":           args.default,
        "io.k8s.display-name":  args.default,
        "io.k8s.description":   args.default,
    }

    content = path.read_text()
    current = _parse_labels(content)
    missing = {k: v for k, v in expected.items() if current.get(k) != v}

    if not missing:
        print("All mandatory RHOAI labels are already present and correct.")
        sys.exit(0)

    print(f"Labels to add/fix: {', '.join(missing.keys())}")

    # Build a new LABEL block with only the missing/incorrect labels
    label_lines = " \\\n      ".join(f'{k}="{v}"' for k, v in missing.items())
    new_block = f"\nLABEL {label_lines}\n"

    # Insert after the last FROM instruction if possible; otherwise append at end
    lines = content.splitlines(keepends=True)
    last_from = -1
    for i, line in enumerate(lines):
        if re.match(r'^FROM\s', line):
            last_from = i

    if last_from >= 0:
        lines.insert(last_from + 1, new_block)
        new_content = "".join(lines)
    else:
        new_content = content.rstrip() + new_block

    path.write_text(new_content)

    # Verify
    verified = _parse_labels(new_content)
    failed = [k for k, v in expected.items() if verified.get(k) != v]
    if failed:
        print(f"ERROR: Verification failed for labels: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)

    print(f"Updated {path}: added/fixed {len(missing)} label(s).")


if __name__ == "__main__":
    main()
