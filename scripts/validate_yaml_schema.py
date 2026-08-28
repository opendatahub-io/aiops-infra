#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "jsonschema>=4.23.0",
#     "pyyaml>=6.0.0",
# ]
# ///
"""
Validate a YAML file against a JSON Schema (Draft 2020-12).

Loads a YAML file and a JSON Schema file, then validates the YAML data against
the schema using jsonschema's Draft 2020-12 validator. Collects ALL validation
errors before reporting, so the engineer sees the complete list of problems in
one run rather than one error at a time.

Usage:
  validate_yaml_schema.py <yaml_file> <schema_file>

Arguments:
  yaml_file     Path to the YAML file to validate (e.g., component_onboarding_details.yaml)
  schema_file   Path to the JSON Schema file (e.g., component_onboarding_details.schema.json)

Output (stdout):
  On success:  "Validation passed."
  On failure:  Error summary to stderr, one validation error per line

Exit codes:
  0  Validation passed
  1  Validation failed or file load error
"""

import argparse
import json
import sys
from pathlib import Path

import jsonschema
import yaml
from jsonschema import Draft202012Validator


def load_yaml(path: Path) -> object:
    """Load and parse a YAML file. Exits with code 1 on error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"ERROR: Cannot read YAML file '{path}': {e}", file=sys.stderr)
        sys.exit(1)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        print(f"ERROR: Failed to parse YAML file '{path}': {e}", file=sys.stderr)
        sys.exit(1)
    if data is None:
        print(f"ERROR: YAML file '{path}' is empty.", file=sys.stderr)
        sys.exit(1)
    return data


def load_schema(path: Path) -> dict:
    """Load and parse a JSON Schema file. Exits with code 1 on error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"ERROR: Cannot read schema file '{path}': {e}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse JSON schema '{path}': {e}", file=sys.stderr)
        sys.exit(1)


def format_error(error: jsonschema.ValidationError) -> str:
    """Format a single validation error as a human-readable string.

    Produces lines in the form:
      - inputs.<field_path>: <message>

    For example:
      - inputs.component_name: 'my component' does not match '^[a-z0-9]+(-[a-z0-9]+)*$'
      - inputs.operator_manifest_src_path: 'operator_manifest_src_path' is a required property
    """
    path_parts = list(error.absolute_path)
    if path_parts:
        field_path = ""
        for part in path_parts:
            if isinstance(part, int):
                field_path += f"[{part}]"
            elif field_path:
                field_path += f".{part}"
            else:
                field_path = str(part)
        label = field_path if field_path.startswith("inputs") else f"inputs.{field_path}"
    else:
        label = "inputs"

    message = error.message
    if error.validator == "not":
        description = error.schema.get("description") if isinstance(error.schema, dict) else None
        if description:
            message = f"{error.instance!r} is invalid. {description}"

    return f"  - {label}: {message}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("yaml_file", help="Path to the YAML file to validate")
    parser.add_argument("schema_file", help="Path to the JSON Schema file")
    args = parser.parse_args()

    yaml_path = Path(args.yaml_file)
    schema_path = Path(args.schema_file)

    if not yaml_path.exists():
        print(f"ERROR: YAML file does not exist: {yaml_path}", file=sys.stderr)
        sys.exit(1)
    if not schema_path.exists():
        print(f"ERROR: Schema file does not exist: {schema_path}", file=sys.stderr)
        sys.exit(1)

    data = load_yaml(yaml_path)
    schema = load_schema(schema_path)

    # Collect ALL errors before reporting (do not stop at first)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))

    if not errors:
        print("Validation passed.")
        sys.exit(0)

    print(f"Validation failed: {len(errors)} error(s) found in '{yaml_path}':", file=sys.stderr)
    for error in errors:
        print(format_error(error), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
