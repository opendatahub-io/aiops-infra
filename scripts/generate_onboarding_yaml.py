#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Write component_onboarding_details.yaml from CLI arguments."""

import argparse
import sys
from pathlib import Path

_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from upsert_team_slack_handle import HANDLE_RE, normalize_channel, normalize_handle  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Generate component_onboarding_details.yaml")
    p.add_argument("--output", required=True, help="Output file path")
    p.add_argument("--product-context", required=True, choices=["ODH", "RHOAI"])
    p.add_argument("--component-name", required=True)
    p.add_argument("--repo-url", required=True)
    p.add_argument("--repo-branch", required=True)
    p.add_argument("--context-path", required=True)
    p.add_argument("--dockerfile-path", required=True)
    p.add_argument("--build-type", choices=["CI", "Release"], help="ODH only")
    p.add_argument("--odh-release-tag", help="ODH Release builds only: version tag (e.g. 2.21.0)")
    p.add_argument("--architectures", help="RHOAI only; comma-separated (default: x86_64,arm64)")
    p.add_argument("--target-rhoai-version", help="RHOAI only")
    p.add_argument("--long-description", help="RHOAI only")
    p.add_argument("--short-description", help="RHOAI only")
    p.add_argument("--release-category", choices=["Generally Available", "Tech Preview"], help="RHOAI only")
    p.add_argument("--is-operator", action="store_true", default=False)
    p.add_argument("--operator-manifest-src-path")
    p.add_argument("--operator-manifest-dest-path")
    p.add_argument("--operator-manifest-type", choices=["chart"], help="Optional Helm chart operator type")
    p.add_argument(
        "--slack-team-handle",
        required=True,
        help="Slack user-group handle for the team responsible for this component (e.g. ai-core-platform)",
    )
    p.add_argument(
        "--slack-team-channel",
        help="Optional Slack channel name for this component's team",
    )
    args = p.parse_args()

    slack_team_handle = normalize_handle(args.slack_team_handle)
    if not HANDLE_RE.match(slack_team_handle):
        print(
            f"ERROR: --slack-team-handle '{args.slack_team_handle}' is invalid. "
            "Use a lowercase Slack user-group handle such as ai-core-platform.",
            file=sys.stderr,
        )
        sys.exit(1)
    slack_team_channel = normalize_channel(args.slack_team_channel)

    product = args.product_context
    lines = ["inputs:"]
    lines.append(f"  product_context: {product}")
    lines.append(f"  component_name: {args.component_name}")
    lines.append(f"  repo_url: {args.repo_url}")
    lines.append(f"  repo_branch: {args.repo_branch}")
    lines.append(f"  context_path: {args.context_path}")
    lines.append(f"  dockerfile_path: {args.dockerfile_path}")

    dockerfile_name = args.dockerfile_path.split("/")[-1]
    if product == "RHOAI" and not "Dockerfile.konflux" in dockerfile_name:
        print(
            f"ERROR: For RHOAI, the Dockerfile name must contain 'Dockerfile.konflux' "
            f"(got '{dockerfile_name}')",
            file=sys.stderr,
        )
        sys.exit(1)

    if product == "ODH":
        if not args.build_type:
            print("ERROR: --build-type is required for ODH", file=sys.stderr)
            sys.exit(1)
        lines.append(f"  build_type: {args.build_type}")
        if args.build_type == "Release":
            if not args.odh_release_tag:
                print("ERROR: --odh-release-tag is required for ODH Release builds", file=sys.stderr)
                sys.exit(1)
            lines.append(f"  odh_release_tag: {args.odh_release_tag}")
    else:
        if not args.target_rhoai_version:
            print("ERROR: --target-rhoai-version is required for RHOAI", file=sys.stderr)
            sys.exit(1)
        if not args.release_category:
            print("ERROR: --release-category is required for RHOAI", file=sys.stderr)
            sys.exit(1)
        archs = [a.strip() for a in (args.architectures or "x86_64,arm64").split(",")]
        lines.append("  architectures:")
        for arch in archs:
            lines.append(f"    - {arch}")
        lines.append(f"  target_rhoai_version: {args.target_rhoai_version}")
        lines.append(f"  release_category: \"{args.release_category}\"")
        lines.append(f"  long_description: {args.long_description or ''}")
        lines.append(f"  short_description: {args.short_description or ''}")

    lines.append(f"  is_operator: {str(args.is_operator).lower()}")
    lines.append(f"  slack_team_handle: {slack_team_handle}")
    if slack_team_channel:
        lines.append(f"  slack_team_channel: {slack_team_channel}")

    if args.is_operator:
        if not args.operator_manifest_src_path or not args.operator_manifest_dest_path:
            print("ERROR: --operator-manifest-src-path and --operator-manifest-dest-path are required when --is-operator", file=sys.stderr)
            sys.exit(1)
        lines.append(f"  operator_manifest_src_path: {args.operator_manifest_src_path}")
        lines.append(f"  operator_manifest_dest_path: {args.operator_manifest_dest_path}")
        if args.operator_manifest_type:
            lines.append(f"  operator_manifest_type: {args.operator_manifest_type}")

    with open(args.output, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"YAML written to: {args.output}")


if __name__ == "__main__":
    main()
