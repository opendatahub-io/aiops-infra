#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["ruamel.yaml"]
# ///
"""
YAML editing utility with ruamel.yaml (preserves comments and formatting).

Subcommands:
  append-items-array      <file> --name <n> --description <d> [--public]
  append-yaml-doc         <file> --yaml-string <str>
  insert-map-key          <file> --map-key <parent> --name <n> --src <s> --dest <d>
  append-array-entry      <file> --array-key <k> --name <n> --value <v> [--component <c>]
  insert-list-item        <file> --list-key <k> --value <v>
  append-rpa-component    <file> --array-key <k> --name <n> --url <u>
  insert-simple-map-entry <file> --map-key <dot.path.0.nested> --key <k> --value <v>
  append-renovate-repo    <file> --renovate-config <cfg> --name <entry>
"""
import argparse
import sys
from pathlib import Path
from ruamel.yaml import YAML


def _load(path: Path, yaml: YAML):
    with path.open() as f:
        return yaml.load(f)


def _save(path: Path, data, yaml: YAML):
    with path.open("w") as f:
        yaml.dump(data, f)


def cmd_append_items_array(args):
    """Append an entry to a top-level 'items' sequence."""
    yaml = YAML()
    yaml.preserve_quotes = True
    path = Path(args.file)
    data = _load(path, yaml)

    entry = {"name": args.name, "description": args.description}
    if args.public:
        entry["public"] = True

    if "items" not in data or data["items"] is None:
        data["items"] = []
    data["items"].append(entry)
    _save(path, data, yaml)
    print(f"Appended '{args.name}' to items array in {path}")


def cmd_append_yaml_doc(args):
    """Append a YAML document block to a multi-document YAML file."""
    yaml = YAML()
    yaml.preserve_quotes = True
    path = Path(args.file)

    new_doc = yaml.load(args.yaml_string)
    docs = []
    with path.open() as f:
        for doc in yaml.load_all(f):
            docs.append(doc)

    docs.append(new_doc)

    with path.open("w") as f:
        yaml.dump_all(docs, f)
    print(f"Appended YAML document to {path}")


def cmd_insert_map_key(args):
    """Insert a key into a nested map at the given parent key."""
    yaml = YAML()
    yaml.preserve_quotes = True
    path = Path(args.file)
    data = _load(path, yaml)

    # Navigate to the map key (supports dot notation)
    parts = args.map_key.split(".")
    node = data
    for part in parts:
        if part not in node:
            node[part] = {}
        node = node[part]

    node[args.name] = {"src": args.src, "dest": args.dest}
    _save(path, data, yaml)
    print(f"Inserted key '{args.name}' under '{args.map_key}' in {path}")


def cmd_append_array_entry(args):
    """Append an object entry to a nested array."""
    yaml = YAML()
    yaml.preserve_quotes = True
    path = Path(args.file)
    data = _load(path, yaml)

    # Navigate dot-path to the array
    parts = args.array_key.split(".")
    node = data
    for part in parts:
        if part not in node or node[part] is None:
            node[part] = []
        node = node[part]

    if not isinstance(node, list):
        print(f"ERROR: '{args.array_key}' is not a list in {path}", file=sys.stderr)
        sys.exit(1)

    entry = {"name": args.name, "value": args.value}
    if getattr(args, "component", None):
        entry["component"] = args.component
    node.append(entry)
    _save(path, data, yaml)
    print(f"Appended entry '{args.name}' to '{args.array_key}' in {path}")


def cmd_append_rpa_component(args):
    """Append a ReleasePlanAdmission component entry {name, repositories: [{url}]} to a nested array."""
    yaml = YAML()
    yaml.preserve_quotes = True
    path = Path(args.file)
    data = _load(path, yaml)

    parts = args.array_key.split(".")
    node = data
    for part in parts:
        if part not in node or node[part] is None:
            node[part] = []
        node = node[part]

    if not isinstance(node, list):
        print(f"ERROR: '{args.array_key}' is not a list in {path}", file=sys.stderr)
        sys.exit(1)

    node.append({"name": args.name, "repositories": [{"url": args.url}]})
    _save(path, data, yaml)
    print(f"Appended RPA component '{args.name}' to '{args.array_key}' in {path}")


def cmd_insert_simple_map_entry(args):
    """Set a simple key=value string pair in a nested map (supports integer indices in dot-path)."""
    yaml = YAML()
    yaml.preserve_quotes = True
    path = Path(args.file)
    data = _load(path, yaml)

    parts = args.map_key.split(".")
    node = data
    for part in parts:
        if part.isdigit():
            node = node[int(part)]
        else:
            if part not in node or node[part] is None:
                node[part] = {}
            node = node[part]

    if not isinstance(node, dict):
        print(f"ERROR: '{args.map_key}' is not a map in {path}", file=sys.stderr)
        sys.exit(1)

    node[args.key] = args.value
    _save(path, data, yaml)
    print(f"Set '{args.key}' = '{args.value}' under '{args.map_key}' in {path}")


def cmd_insert_list_item(args):
    """Insert a scalar value into a list at the given key."""
    yaml = YAML()
    yaml.preserve_quotes = True
    path = Path(args.file)
    data = _load(path, yaml)

    parts = args.list_key.split(".")
    node = data
    for part in parts:
        if part not in node or node[part] is None:
            node[part] = []
        node = node[part]

    if not isinstance(node, list):
        print(f"ERROR: '{args.list_key}' is not a list in {path}", file=sys.stderr)
        sys.exit(1)

    if args.value not in node:
        node.append(args.value)
    _save(path, data, yaml)
    print(f"Inserted '{args.value}' into '{args.list_key}' in {path}")


def cmd_append_renovate_repo(args):
    """Append a sync-repositories entry to the first matching renovate distribution group."""
    yaml = YAML()
    yaml.preserve_quotes = True
    path = Path(args.file)
    data = _load(path, yaml)

    if not isinstance(data, list):
        print(f"ERROR: {path} top-level is not a list", file=sys.stderr)
        sys.exit(1)

    target_group = None
    for group in data:
        if isinstance(group, dict) and group.get("renovate-config") == args.renovate_config:
            target_group = group
            break

    if target_group is None:
        print(f"ERROR: No group with renovate-config='{args.renovate_config}' found in {path}", file=sys.stderr)
        sys.exit(1)

    repos = target_group.setdefault("sync-repositories", [])
    existing_names = [r.get("name", "") for r in repos if isinstance(r, dict)]
    if args.name in existing_names:
        print(f"'{args.name}' already present in sync-repositories — skipping.")
        return

    repos.append({"name": args.name})
    _save(path, data, yaml)
    print(f"Appended '{args.name}' to sync-repositories in {path}")


def main():
    parser = argparse.ArgumentParser(description="YAML editing utility")
    sub = parser.add_subparsers(dest="command", required=True)

    # append-items-array
    p1 = sub.add_parser("append-items-array")
    p1.add_argument("file")
    p1.add_argument("--name", required=True)
    p1.add_argument("--description", required=True)
    p1.add_argument("--public", action="store_true")

    # append-yaml-doc
    p2 = sub.add_parser("append-yaml-doc")
    p2.add_argument("file")
    p2.add_argument("--yaml-string", required=True)

    # insert-map-key
    p3 = sub.add_parser("insert-map-key")
    p3.add_argument("file")
    p3.add_argument("--map-key", required=True)
    p3.add_argument("--name", required=True)
    p3.add_argument("--src", required=True)
    p3.add_argument("--dest", required=True)

    # append-array-entry
    p4 = sub.add_parser("append-array-entry")
    p4.add_argument("file")
    p4.add_argument("--array-key", required=True)
    p4.add_argument("--name", required=True)
    p4.add_argument("--value", required=True)
    p4.add_argument("--component", default=None)

    # insert-list-item
    p5 = sub.add_parser("insert-list-item")
    p5.add_argument("file")
    p5.add_argument("--list-key", required=True)
    p5.add_argument("--value", required=True)

    # append-rpa-component
    p6 = sub.add_parser("append-rpa-component")
    p6.add_argument("file")
    p6.add_argument("--array-key", required=True)
    p6.add_argument("--name", required=True)
    p6.add_argument("--url", required=True)

    # insert-simple-map-entry
    p7 = sub.add_parser("insert-simple-map-entry")
    p7.add_argument("file")
    p7.add_argument("--map-key", required=True)
    p7.add_argument("--key", required=True)
    p7.add_argument("--value", required=True)

    # append-renovate-repo
    p8 = sub.add_parser("append-renovate-repo")
    p8.add_argument("file")
    p8.add_argument("--renovate-config", required=True)
    p8.add_argument("--name", required=True)

    args = parser.parse_args()

    dispatch = {
        "append-items-array":      cmd_append_items_array,
        "append-yaml-doc":         cmd_append_yaml_doc,
        "insert-map-key":          cmd_insert_map_key,
        "append-array-entry":      cmd_append_array_entry,
        "insert-list-item":        cmd_insert_list_item,
        "append-rpa-component":    cmd_append_rpa_component,
        "insert-simple-map-entry": cmd_insert_simple_map_entry,
        "append-renovate-repo":    cmd_append_renovate_repo,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
