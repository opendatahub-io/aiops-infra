#!/usr/bin/env python3
"""
Append a scalar value to a YAML list using plain text manipulation.

Unlike edit_yaml.py (which uses ruamel.yaml), this script performs
byte-level insertion so it never reformats unrelated parts of the file.
Use this for YAML files with mixed indentation that ruamel.yaml would
disturb.

Usage:
    python3 append_yaml_list_entry.py <file> --list-key <key> --value <value>

Example:
    python3 append_yaml_list_entry.py rhoai.yaml \
        --list-key repositories \
        --value "registry.access.redhat.com/rhoai/my-component-rhel9"
"""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Append a value to a YAML list (text-based)")
    parser.add_argument("file", help="Path to the YAML file")
    parser.add_argument("--list-key", required=True, help="YAML key whose list to append to")
    parser.add_argument("--value", required=True, help="Scalar value to append")
    args = parser.parse_args()

    with open(args.file, "r") as f:
        lines = f.readlines()

    in_list = False
    last_item_idx = None
    indent = "  "

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{args.list_key}:"):
            in_list = True
        elif in_list and line.lstrip().startswith("- "):
            last_item_idx = i
            indent = line[: len(line) - len(line.lstrip())]
        elif in_list and stripped and not line.lstrip().startswith("- ") and not stripped.startswith("#"):
            in_list = False

    entry_line = f"{indent}- {args.value}\n"

    if last_item_idx is not None:
        if args.value in lines[last_item_idx]:
            print(f"'{args.value}' already present — skipping.")
            return
        lines.insert(last_item_idx + 1, entry_line)
    else:
        lines.append(entry_line)

    with open(args.file, "w") as f:
        f.writelines(lines)
    print(f"Appended '{args.value}' to '{args.list_key}' in {args.file}")


if __name__ == "__main__":
    main()
