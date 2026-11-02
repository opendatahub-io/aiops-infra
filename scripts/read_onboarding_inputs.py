#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyyaml>=6.0.0"]
# ///
"""Read onboarding inputs as YAML and emit safely quoted shell assignments."""

import argparse
import shlex
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml_file", type=Path)
    args = parser.parse_args()
    try:
        data = yaml.safe_load(args.yaml_file.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("inputs"), dict):
            raise ValueError("expected an inputs mapping")
        inputs = data["inputs"]
        values = {}
        for field, variable, default in [
            ("component_name", "COMPONENT_NAME", ""),
            ("repo_url", "REPO_URL", ""),
            ("repo_branch", "REPO_BRANCH", ""),
            ("product_context", "YAML_PC", ""),
            ("release_category", "RELEASE_CATEGORY", "Generally Available"),
        ]:
            value = inputs.get(field, default)
            if not isinstance(value, str):
                raise ValueError(f"inputs.{field} must be a string")
            values[variable] = value
        is_operator = inputs.get("is_operator", False)
        if not isinstance(is_operator, bool):
            raise ValueError("inputs.is_operator must be a boolean")
        values["IS_OPERATOR"] = str(is_operator).lower()
        present = "base_rhel_version" in inputs
        os_value = inputs.get("base_rhel_version", "")
        if not isinstance(os_value, str):
            raise ValueError("inputs.base_rhel_version must be rhel9 or rhel10")
        values["BASE_RHEL_VERSION_PRESENT"] = str(present).lower()
        values["BASE_RHEL_VERSION_INPUT"] = os_value
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(1, f"ERROR: Cannot read onboarding inputs: {exc}\n")
    for name, value in values.items():
        print(f"{name}={shlex.quote(value)}")


if __name__ == "__main__":
    main()
