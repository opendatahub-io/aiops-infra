#!/usr/bin/env python3
# /// script
# dependencies = ["ruamel.yaml>=0.18,<0.19"]
# ///
"""Multi-purpose YAML editing script that preserves formatting and comments.

Operations:
  append-items-array  Append {name,description,public} to top-level items: array
  append-yaml-doc     Append a YAML document (adds --- separator)
  insert-map-key      Insert key under a map in alphabetical order
  append-array-entry  Append {name,value} to a named array (dot notation)
  insert-list-item    Insert a value into a list in alphabetical order

All operations are idempotent (skip if entry already exists).
"""

import argparse
import sys
from pathlib import Path


def _load_yaml():
    from ruamel.yaml import YAML
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    return y


def _navigate(data, dotpath):
    """Walk dot-separated key path and return the target node."""
    target = data
    for k in dotpath.split("."):
        target = target[k]
    return target


def append_items_array(file_path, name, description, public):
    """Append an entry to the top-level items: list."""
    y = _load_yaml()
    p = Path(file_path)
    data = y.load(p)
    if "items" not in data:
        data["items"] = []
    for item in data["items"]:
        if item.get("name") == name:
            print(f"Item '{name}' already present in items array — skipping.", file=sys.stderr)
            return 0
    data["items"].append({"name": name, "description": description, "public": public})
    y.dump(data, p)
    print(f"Appended item '{name}' to items array in {file_path}")
    return 0


def append_yaml_doc(file_path, yaml_string):
    """Append a YAML document to a file, adding a --- separator."""
    p = Path(file_path)
    content = yaml_string.strip()
    with p.open("a") as f:
        f.write("\n---\n")
        f.write(content)
        f.write("\n")
    print(f"Appended YAML document to {file_path}")
    return 0


def insert_map_key(file_path, map_key, name, src, dest):
    """Insert a component entry under map_key in alphabetical order."""
    from ruamel.yaml.comments import CommentedMap
    y = _load_yaml()
    p = Path(file_path)
    data = y.load(p)
    target = _navigate(data, map_key)
    if name in target:
        print(f"Key '{name}' already present under '{map_key}' — skipping.", file=sys.stderr)
        return 0
    entry = CommentedMap()
    entry["src"] = src
    entry["dest"] = dest
    all_keys = sorted(list(target.keys()) + [name])
    new_map = CommentedMap()
    for k in all_keys:
        new_map[k] = entry if k == name else target[k]
    target.clear()
    target.update(new_map)
    y.dump(data, p)
    print(f"Inserted key '{name}' under '{map_key}' in alphabetical order in {file_path}")
    return 0


def append_array_entry(file_path, array_key, name, value):
    """Append {name,value} to a named array (dot-notation path)."""
    y = _load_yaml()
    p = Path(file_path)
    data = y.load(p)
    target = _navigate(data, array_key)
    for item in target:
        if isinstance(item, dict) and item.get("name") == name:
            print(f"Entry '{name}' already present in '{array_key}' — skipping.", file=sys.stderr)
            return 0
    target.append({"name": name, "value": value})
    y.dump(data, p)
    print(f"Appended entry '{name}' to array '{array_key}' in {file_path}")
    return 0


def insert_list_item(file_path, list_key, value):
    """Insert value into a list in alphabetical order (dot-notation path)."""
    y = _load_yaml()
    p = Path(file_path)
    data = y.load(p)
    target = _navigate(data, list_key)
    if value in target:
        print(f"Value '{value}' already present in list '{list_key}' — skipping.", file=sys.stderr)
        return 0
    target.append(value)
    target.sort()
    y.dump(data, p)
    print(f"Inserted '{value}' into list '{list_key}' in alphabetical order in {file_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Multi-purpose YAML editor (preserves formatting)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="op", required=True, metavar="operation")

    p_aia = sub.add_parser("append-items-array", help="Append to top-level items: array")
    p_aia.add_argument("file")
    p_aia.add_argument("--name", required=True)
    p_aia.add_argument("--description", required=True)
    p_aia.add_argument("--public", action="store_true", default=False)

    p_ayd = sub.add_parser("append-yaml-doc", help="Append a YAML document (--- separator)")
    p_ayd.add_argument("file")
    p_ayd.add_argument("--yaml-string", required=True, help="YAML document content to append")

    p_imk = sub.add_parser("insert-map-key", help="Insert key under a map in alphabetical order")
    p_imk.add_argument("file")
    p_imk.add_argument("--map-key", required=True, help="Dot-notation path to parent map (e.g. map)")
    p_imk.add_argument("--name", required=True, help="Component/key name to insert")
    p_imk.add_argument("--src", required=True)
    p_imk.add_argument("--dest", required=True)

    p_aae = sub.add_parser("append-array-entry", help="Append {name,value} to a named array")
    p_aae.add_argument("file")
    p_aae.add_argument("--array-key", required=True, help="Dot-notation path (e.g. patch.relatedImages)")
    p_aae.add_argument("--name", required=True)
    p_aae.add_argument("--value", required=True)

    p_ili = sub.add_parser("insert-list-item", help="Insert value into a list alphabetically")
    p_ili.add_argument("file")
    p_ili.add_argument("--list-key", required=True, help="Dot-notation path to list")
    p_ili.add_argument("--value", required=True)

    args = parser.parse_args()

    try:
        if args.op == "append-items-array":
            sys.exit(append_items_array(args.file, args.name, args.description, args.public))
        elif args.op == "append-yaml-doc":
            sys.exit(append_yaml_doc(args.file, args.yaml_string))
        elif args.op == "insert-map-key":
            sys.exit(insert_map_key(args.file, args.map_key, args.name, args.src, args.dest))
        elif args.op == "append-array-entry":
            sys.exit(append_array_entry(args.file, args.array_key, args.name, args.value))
        elif args.op == "insert-list-item":
            sys.exit(insert_list_item(args.file, args.list_key, args.value))
    except KeyError as e:
        print(f"ERROR: Key {e} not found in YAML file. Check the path.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
