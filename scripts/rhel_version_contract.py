#!/usr/bin/env python3
"""Read the supported RHEL values and legacy fallback from the JSON schema."""

import json
import re
from pathlib import Path
from typing import Optional


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "component_onboarding_details.schema.json"


def rhel_version_schema(schema_path: Optional[Path] = None) -> tuple[list[str], str]:
    path = schema_path or SCHEMA_PATH
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        version_schema = schema["properties"]["inputs"]["properties"]["base_rhel_version"]
        allowed = version_schema["enum"]
        default = version_schema["default"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read base_rhel_version enum/default from schema {path}: {exc}") from exc

    if (
        not isinstance(allowed, list)
        or not allowed
        or any(not isinstance(value, str) or not re.fullmatch(r"rhel[1-9][0-9]*", value) for value in allowed)
    ):
        raise ValueError("schema base_rhel_version.enum must be a non-empty list of rhel<positive-major> strings")
    if not isinstance(default, str) or default not in allowed:
        raise ValueError("schema base_rhel_version.default must be included in base_rhel_version.enum")
    return allowed, default


def resolve_base_rhel_version(version: Optional[str] = None, schema_path: Optional[Path] = None) -> str:
    allowed, default = rhel_version_schema(schema_path)
    selected = default if version is None else version
    if selected not in allowed:
        choices = ", ".join(allowed)
        raise ValueError(f"base_rhel_version {selected!r} is not supported by the schema; allowed values: {choices}")
    return selected
