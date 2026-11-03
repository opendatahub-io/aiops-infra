#!/usr/bin/env python3
"""Resolve RHOAI's base RHEL version and image repository suffix.

The schema restricts currently supported onboarding values. This naming helper
deliberately accepts any positive numeric major so callers remain data-driven.
"""

import argparse
import shlex
from typing import Optional

from rhel_version_contract import resolve_base_rhel_version


def resolve(product_context: str, base_rhel_version: Optional[str] = None) -> tuple[str, str]:
    if product_context == "ODH":
        if base_rhel_version is not None:
            raise ValueError("ODH must not set base_rhel_version")
        return "", ""
    if product_context != "RHOAI":
        raise ValueError("product_context must be ODH or RHOAI")

    version = resolve_base_rhel_version(base_rhel_version)
    return version, f"-{version}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-context", required=True, choices=("ODH", "RHOAI"))
    parser.add_argument("--base-rhel-version", help="RHOAI base OS; legacy tickets use the schema default")
    args = parser.parse_args()
    try:
        version, suffix = resolve(args.product_context, args.base_rhel_version)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"BASE_RHEL_VERSION={shlex.quote(version)}")
    print(f"IMAGE_REPO_SUFFIX={shlex.quote(suffix)}")


if __name__ == "__main__":
    main()
