#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["ruamel.yaml"]
# ///
"""
YAML editing utility with ruamel.yaml (preserves comments and formatting).

Subcommands:
  append-items-array      <file> --name <n> --description <d> [--public|--no-public]
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


def _detect_formatting(path: Path) -> dict:
    """Detect explicit_start and sequence indent from an existing YAML file."""
    import re
    raw = path.read_text()
    lines = raw.splitlines()
    info: dict = {"explicit_start": False, "map_indent": 2, "seq_indent": 2, "seq_offset": 0}

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "---":
            info["explicit_start"] = True
        break

    # Detect mapping indent from the first indented non-comment, non-sequence line
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        leading = len(line) - len(stripped)
        if leading > 0:
            info["map_indent"] = leading
            break

    # Detect sequence indent relative to its parent mapping key.
    # Walk lines to find "key:\n  - item" patterns.  Pick the deepest
    # (most-indented) parent whose child is a sequence item, since that
    # is the nesting level most sensitive to ruamel.yaml's indent setting.
    best_offset = 0
    best_parent_col = -1
    parent_col: int | None = None
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        # Check sequence item first (e.g. "    - repo_mappings:") so it
        # isn't misidentified as a mapping key by the pattern below.
        m_seq = re.match(r'^( *)- ', line)
        if m_seq:
            if parent_col is not None:
                dash_col = len(m_seq.group(1))
                offset = dash_col - parent_col
                if offset > 0 and parent_col > best_parent_col:
                    best_parent_col = parent_col
                    best_offset = offset
                parent_col = None
            continue
        m_key = re.match(r'^( *)\S[^#]*:\s*$', line)
        if m_key:
            parent_col = len(m_key.group(1))

    if best_offset > 0:
        info["seq_indent"] = best_offset + 2
        info["seq_offset"] = best_offset

    return info


def _make_yaml(path: Path) -> YAML:
    """Create a YAML instance configured to match the file's existing formatting."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096

    if path.exists():
        fmt = _detect_formatting(path)
        yaml.explicit_start = fmt["explicit_start"]
        yaml.indent(mapping=fmt["map_indent"], sequence=fmt["seq_indent"], offset=fmt["seq_offset"])

    return yaml


def _load(path: Path, yaml: YAML):
    with path.open() as f:
        return yaml.load(f)


def _save(path: Path, data, yaml: YAML):
    import io
    buf = io.BytesIO()
    yaml.dump(data, buf)
    output = buf.getvalue().decode("utf-8")

    # ruamel.yaml applies seq_offset globally, which can indent top-level
    # list items when the offset was detected from a deeper nesting level.
    # Fix: if the file originally started with "- " at column 0 but the
    # output has leading whitespace before "- ", strip that extra indent.
    if path.exists():
        orig = path.read_text()
        orig_lines = orig.splitlines()
        first_orig = next((l for l in orig_lines if l.strip() and not l.strip().startswith("#")), "")
        out_lines = output.splitlines(True)
        first_out = next((l for l in out_lines if l.strip() and not l.strip().startswith("#")), "")

        if first_orig.startswith("- ") and first_out != first_orig[:len(first_out.rstrip())] + "\n":
            import re
            m = re.match(r'^(\s+)', first_out)
            if m:
                extra = m.group(1)
                output = "\n".join(
                    l[len(extra):] if l.startswith(extra) else l
                    for l in output.splitlines()
                ) + "\n"

    path.write_text(output)


def cmd_append_items_array(args):
    """Append an entry to a top-level 'items' sequence."""
    path = Path(args.file)
    yaml = _make_yaml(path)
    data = _load(path, yaml)

    entry = {"name": args.name, "description": args.description}
    if args.public is True:
        entry["public"] = True
    elif args.public is False:
        entry["public"] = False

    if "items" not in data or data["items"] is None:
        data["items"] = []
    data["items"].append(entry)
    _save(path, data, yaml)
    print(f"Appended '{args.name}' to items array in {path}")


def cmd_append_yaml_doc(args):
    """Append a YAML document block to a multi-document YAML file."""
    path = Path(args.file)
    yaml = _make_yaml(path)

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
    path = Path(args.file)
    yaml = _make_yaml(path)
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
    path = Path(args.file)
    yaml = _make_yaml(path)
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
    path = Path(args.file)
    yaml = _make_yaml(path)
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
    path = Path(args.file)
    yaml = _make_yaml(path)
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
    path = Path(args.file)
    yaml = _make_yaml(path)
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
    path = Path(args.file)
    yaml = _make_yaml(path)
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

    # Match quote style of existing entries
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString
    existing_quoted = any(
        isinstance(r.get("name"), DoubleQuotedScalarString) for r in repos if isinstance(r, dict)
    )
    name_val = DoubleQuotedScalarString(args.name) if existing_quoted else args.name

    # ruamel.yaml stores the blank-line separator between top-level groups
    # as a CommentToken on the *last key* of the last mapping in
    # sync-repositories (slot [2] = end-of-value comment).  When we
    # append a new entry, the old last entry keeps its trailing "\n\n",
    # so the new entry appears after the blank line.
    # Fix: steal trailing blank-line tokens from the old last entry and
    # move them to the new entry after appending.
    from ruamel.yaml.comments import CommentedMap
    old_last = repos[-1] if repos else None
    trailing_comment = None
    if old_last is not None and hasattr(old_last, "ca"):
        for key in reversed(list(old_last.keys())):
            if key in old_last.ca.items:
                token = old_last.ca.items[key]
                if token[2] is not None and hasattr(token[2], "value") and "\n" in token[2].value:
                    trailing_comment = token[2]
                    token[2] = None
                    break

    new_entry = CommentedMap([("name", name_val)])
    repos.append(new_entry)

    if trailing_comment is not None:
        new_entry.ca.items["name"] = [None, None, trailing_comment, None]

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
    p1_vis = p1.add_mutually_exclusive_group()
    p1_vis.add_argument("--public", action="store_true", default=None, dest="public")
    p1_vis.add_argument("--no-public", action="store_false", dest="public")

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
