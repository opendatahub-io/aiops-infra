#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Write component_onboarding_details.yaml from CLI arguments."""

import argparse
import sys


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
    p.add_argument("--architectures", help="RHOAI only; comma-separated (default: x86_64,arm64)")
    p.add_argument("--target-rhoai-version", help="RHOAI only")
    p.add_argument("--long-description", help="RHOAI only")
    p.add_argument("--short-description", help="RHOAI only")
    p.add_argument("--is-operator", action="store_true", default=False)
    p.add_argument("--operator-manifest-src-path")
    p.add_argument("--operator-manifest-dest-path")
    args = p.parse_args()

    product = args.product_context
    lines = ["inputs:"]
    lines.append(f"  product_context: {product}")
    lines.append(f"  component_name: {args.component_name}")
    lines.append(f"  repo_url: {args.repo_url}")
    lines.append(f"  repo_branch: {args.repo_branch}")
    lines.append(f"  context_path: {args.context_path}")
    lines.append(f"  dockerfile_path: {args.dockerfile_path}")

    dockerfile_name = args.dockerfile_path.split("/")[-1]
    if product == "RHOAI" and not dockerfile_name.startswith("Dockerfile.konflux"):
        print(
            f"ERROR: For RHOAI, the Dockerfile name must start with 'Dockerfile.konflux' "
            f"(got '{dockerfile_name}')",
            file=sys.stderr,
        )
        sys.exit(1)

    if product == "ODH":
        if not args.build_type:
            print("ERROR: --build-type is required for ODH", file=sys.stderr)
            sys.exit(1)
        lines.append(f"  build_type: {args.build_type}")
    else:
        if not args.target_rhoai_version:
            print("ERROR: --target-rhoai-version is required for RHOAI", file=sys.stderr)
            sys.exit(1)
        archs = [a.strip() for a in (args.architectures or "x86_64,arm64").split(",")]
        lines.append("  architectures:")
        for arch in archs:
            lines.append(f"    - {arch}")
        lines.append(f"  target_rhoai_version: {args.target_rhoai_version}")
        lines.append(f"  long_description: {args.long_description or ''}")
        lines.append(f"  short_description: {args.short_description or ''}")

    lines.append(f"  is_operator: {str(args.is_operator).lower()}")

    if args.is_operator:
        if not args.operator_manifest_src_path or not args.operator_manifest_dest_path:
            print("ERROR: --operator-manifest-src-path and --operator-manifest-dest-path are required when --is-operator", file=sys.stderr)
            sys.exit(1)
        lines.append(f"  operator_manifest_src_path: {args.operator_manifest_src_path}")
        lines.append(f"  operator_manifest_dest_path: {args.operator_manifest_dest_path}")

    with open(args.output, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"YAML written to: {args.output}")


if __name__ == "__main__":
    main()
