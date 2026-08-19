#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Write component_offboarding_details.yaml from CLI arguments."""

import argparse
import sys


def main():
    p = argparse.ArgumentParser(description="Generate component_offboarding_details.yaml")
    p.add_argument("--output", required=True, help="Output file path")
    p.add_argument("--product-context", required=True, choices=["ODH", "RHOAI"])
    p.add_argument("--component-name", required=True)
    p.add_argument("--repo-url", required=True)
    p.add_argument("--build-type", choices=["CI", "Release"], help="ODH only")
    p.add_argument("--target-rhoai-version", help="RHOAI only")
    p.add_argument("--is-operator", action="store_true", default=False)
    p.add_argument("--fully-deprecated", action="store_true", default=False)
    args = p.parse_args()

    product = args.product_context
    lines = ["inputs:"]
    lines.append(f"  product_context: {product}")
    lines.append(f"  component_name: {args.component_name}")
    lines.append(f"  repo_url: {args.repo_url}")

    if product == "ODH":
        if not args.build_type:
            print("ERROR: --build-type is required for ODH", file=sys.stderr)
            sys.exit(1)
        lines.append(f"  build_type: {args.build_type}")
    else:
        if not args.target_rhoai_version:
            print("ERROR: --target-rhoai-version is required for RHOAI", file=sys.stderr)
            sys.exit(1)
        lines.append(f"  target_rhoai_version: {args.target_rhoai_version}")

    lines.append(f"  is_operator: {str(args.is_operator).lower()}")
    lines.append(f"  fully_deprecated: {str(args.fully_deprecated).lower()}")

    with open(args.output, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"YAML written to: {args.output}")


if __name__ == "__main__":
    main()
