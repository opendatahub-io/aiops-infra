#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyyaml==6.0.3"]
# ///
"""Read onboarding YAML and emit safely quoted shell assignments."""

import argparse
import shlex
from pathlib import Path

import yaml


def read_values(path: Path) -> dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("inputs"), dict):
        raise ValueError("expected an inputs mapping")
    inputs = data["inputs"]
    values: dict[str, str] = {}
    for field, name, default in (
        ("component_name", "COMPONENT_NAME", ""),
        ("repo_url", "REPO_URL", ""),
        ("repo_branch", "REPO_BRANCH", ""),
        ("context_path", "CONTEXT_PATH", ""),
        ("dockerfile_path", "DOCKERFILE_PATH", ""),
        ("target_rhoai_version", "TARGET_RHOAI_VERSION", ""),
        ("product_context", "YAML_PC", ""),
        ("release_category", "RELEASE_CATEGORY", "Generally Available"),
        ("short_description", "SHORT_DESCRIPTION", ""),
        ("long_description", "LONG_DESCRIPTION", ""),
    ):
        value = inputs.get(field, default)
        if not isinstance(value, str):
            raise ValueError(f"inputs.{field} must be a string")
        values[name] = value
    architectures = inputs.get("architectures", [])
    if not isinstance(architectures, list) or any(not isinstance(item, str) for item in architectures):
        raise ValueError("inputs.architectures must be a list of strings")
    values["ARCHITECTURES_CSV"] = ",".join(architectures)
    is_operator = inputs.get("is_operator", False)
    if not isinstance(is_operator, bool):
        raise ValueError("inputs.is_operator must be a boolean")
    values["IS_OPERATOR"] = str(is_operator).lower()
    present = "base_rhel_version" in inputs
    os_value = inputs.get("base_rhel_version", "")
    if not isinstance(os_value, str):
        raise ValueError("inputs.base_rhel_version must be a string")
    values["BASE_RHEL_VERSION_PRESENT"] = str(present).lower()
    values["BASE_RHEL_VERSION_INPUT"] = os_value
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml_file", type=Path)
    args = parser.parse_args()
    try:
        values = read_values(args.yaml_file)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(1, f"ERROR: Cannot read onboarding inputs: {exc}\n")
    for name, value in values.items():
        print(f"{name}={shlex.quote(value)}")


if __name__ == "__main__":
    main()
