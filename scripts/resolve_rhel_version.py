#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Resolve the RHEL version and image suffix using the onboarding schema."""

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Optional


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "component_onboarding_details.schema.json"


def rhel_version_schema(schema_path: Optional[Path] = None) -> list[str]:
    path = schema_path or SCHEMA_PATH
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        version_schema = schema["properties"]["inputs"]["properties"]["base_rhel_version"]
        allowed = version_schema["enum"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read base_rhel_version.enum from schema {path}: {exc}") from exc

    if (
        not isinstance(allowed, list)
        or not allowed
        or any(not isinstance(value, str) or not re.fullmatch(r"rhel[1-9][0-9]*", value) for value in allowed)
    ):
        raise ValueError("schema base_rhel_version.enum must be a non-empty list of rhel<positive-major> strings")
    return allowed


def resolve_base_rhel_version(version: Optional[str] = None, schema_path: Optional[Path] = None) -> str:
    allowed = rhel_version_schema(schema_path)

    # TODO: detect the final runtime-stage base from the selected Dockerfile.
    # Until then, preserve legacy behavior and use RHEL 9 unless the caller
    # supplies a user-confirmed version.
    selected = "rhel9" if version is None else version
    if selected not in allowed:
        choices = ", ".join(allowed)
        raise ValueError(f"base_rhel_version {selected!r} is not supported by the schema; allowed values: {choices}")
    return selected


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
    parser.add_argument("--base-rhel-version", help="Resolved or user-confirmed RHOAI base version")
    args = parser.parse_args()
    try:
        version, suffix = resolve(args.product_context, args.base_rhel_version)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"BASE_RHEL_VERSION={shlex.quote(version)}")
    print(f"IMAGE_REPO_SUFFIX={shlex.quote(suffix)}")


if __name__ == "__main__":
    main()
