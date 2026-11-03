#!/usr/bin/env python3
"""Resolve RHOAI's base RHEL version and image repository suffix.

The schema restricts currently supported onboarding values. This naming helper
deliberately accepts any positive numeric major so callers remain data-driven.
"""

import argparse
import re
import shlex
from typing import Optional


def resolve(product_context: str, base_rhel_version: Optional[str] = None) -> tuple[str, str]:
    if product_context == "ODH":
        if base_rhel_version is not None:
            raise ValueError("ODH must not set base_rhel_version")
        return "", ""
    if product_context != "RHOAI":
        raise ValueError("product_context must be ODH or RHOAI")

    version = "rhel9" if base_rhel_version is None else base_rhel_version
    if not re.fullmatch(r"rhel[1-9][0-9]*", version):
        raise ValueError("base_rhel_version must have the form rhel<positive-major> (e.g. rhel10)")
    return version, f"-{version}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-context", required=True, choices=("ODH", "RHOAI"))
    parser.add_argument("--base-rhel-version", help="RHOAI policy target (defaults to rhel9 for legacy tickets)")
    args = parser.parse_args()
    try:
        version, suffix = resolve(args.product_context, args.base_rhel_version)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"BASE_RHEL_VERSION={shlex.quote(version)}")
    print(f"IMAGE_REPO_SUFFIX={shlex.quote(suffix)}")


if __name__ == "__main__":
    main()
