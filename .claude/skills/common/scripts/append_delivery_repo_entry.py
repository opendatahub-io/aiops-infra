#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Append a delivery repository entry to products/rhoai/rhoai.yaml (idempotent).

Extracted from create-rhoai-delivery-repo SKILL.md Step 8.

Usage:
  uv run --script append_delivery_repo_entry.py \
    --yaml-file <path/to/products/rhoai/rhoai.yaml> \
    --repository-name <repo-name> \
    --content-stream-tag <tag> \
    --display-name <name> \
    --short-description <text> \
    --long-description <text>

Prints "added" or "already-present" to stdout.
Exits 0 on success, 1 on error.
"""
import argparse
import sys
from pathlib import Path

ENTRY_TEMPLATE = """\
- image_type: Layered
  base_rhel_version: rhel9
  repository:
    repository: {repository_name}
    release_categories:
      - Generally Available
    includes_multiple_content_streams: true
    auto_rebuild_tags: []
    content_stream_tags: ['{content_stream_tag}']
    build_categories:
      - Standalone image
    team_id: 617017858ebd9a62aec7c3b8
    display_data:
      name: {display_name}
      short_description: {short_description}
      long_description: {long_description}
    vendor_label: redhat
    application_categories:
      - Developer Tools
    privileged_images_allowed: false
    publish_on_push: true
    documentation_links: []
    contacts:
      *team_contacts
    use_latest: false
    requires_terms: true
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yaml-file",          required=True)
    parser.add_argument("--repository-name",    required=True)
    parser.add_argument("--content-stream-tag", required=True)
    parser.add_argument("--display-name",       required=True)
    parser.add_argument("--short-description",  required=True)
    parser.add_argument("--long-description",   required=True)
    args = parser.parse_args()

    yaml_path = Path(args.yaml_file)
    if not yaml_path.exists():
        print(f"ERROR: {yaml_path} not found", file=sys.stderr)
        sys.exit(1)

    content = yaml_path.read_text()

    marker = f"repository: {args.repository_name}"
    if marker in content:
        print("already-present")
        print(f"Entry for '{args.repository_name}' already present — no changes made.", file=sys.stderr)
        return

    entry = ENTRY_TEMPLATE.format(
        repository_name=args.repository_name,
        content_stream_tag=args.content_stream_tag,
        display_name=args.display_name,
        short_description=args.short_description,
        long_description=args.long_description,
    )

    # Ensure file ends with newline before appending
    if content and not content.endswith("\n"):
        content += "\n"
    content += entry

    yaml_path.write_text(content)

    # Verify
    verification = yaml_path.read_text()
    if marker not in verification:
        print(f"ERROR: Verification failed — '{marker}' not found after append", file=sys.stderr)
        sys.exit(1)
    if f"content_stream_tags: ['{args.content_stream_tag}']" not in verification:
        print(f"ERROR: Verification failed — content_stream_tags not correct after append", file=sys.stderr)
        sys.exit(1)

    print("added")
    print(f"Entry for '{args.repository_name}' appended to {yaml_path}.", file=sys.stderr)


if __name__ == "__main__":
    main()
