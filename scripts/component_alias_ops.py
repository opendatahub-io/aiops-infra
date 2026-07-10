"""component_alias_ops.py -- Component rename alias resolution (dual-mode: CLI + importable).

Loads alias groups from a YAML file and expands component sets so that
coverage matching recognises renamed components (e.g. llama -> ogx).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _repo_root import REPO_ROOT as _REPO_ROOT
DEFAULT_ALIASES_PATH = _REPO_ROOT / "skills" / "references" / "component-aliases.yaml"


def load_aliases(path: str | Path | None = None) -> dict[str, set[str]]:
    """Read alias groups and build a lookup: name -> set of all equivalent names.

    Every name maps to the full group it belongs to (including itself).
    Names that are not in any group are not present in the returned dict;
    callers should treat missing keys as identity (name == itself only).
    """
    import yaml

    resolved = Path(path) if path else DEFAULT_ALIASES_PATH
    if not resolved.exists():
        return {}

    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not data or not isinstance(data.get("alias_groups"), list):
        return {}

    lookup: dict[str, set[str]] = {}
    for group in data["alias_groups"]:
        names = group.get("names")
        if not names or len(names) < 2:
            continue
        name_set = frozenset(names)
        for name in name_set:
            lookup[name] = set(name_set)
    return lookup


def expand_component_set(
    components: set[str] | list[str],
    aliases: dict[str, set[str]],
) -> set[str]:
    """Expand a component set with all known aliases.

    Returns the union of *components* and any aliases found in *aliases*.
    Unknown names pass through unchanged.
    """
    result = set(components)
    for comp in list(components):
        equivalents = aliases.get(comp)
        if equivalents:
            result |= equivalents
    return result


def find_alias_match(
    requested: set[str],
    candidate: str,
    aliases: dict[str, set[str]],
) -> str | None:
    """If *candidate* is not in *requested* but an alias of it is, return that alias.

    Returns the matching requested name, or None if no alias match.
    """
    if candidate in requested:
        return None
    equivalents = aliases.get(candidate)
    if not equivalents:
        return None
    overlap = equivalents & requested
    return next(iter(overlap)) if overlap else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Component rename alias utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    p_expand = sub.add_parser("expand", help="Expand component names with aliases")
    p_expand.add_argument("--components", required=True, help="Comma-separated component names")
    p_expand.add_argument("--aliases-file", default=None)

    p_list = sub.add_parser("list", help="List all alias groups")
    p_list.add_argument("--aliases-file", default=None)

    args = parser.parse_args()

    if args.command == "expand":
        aliases = load_aliases(args.aliases_file)
        components = {c.strip() for c in args.components.split(",")}
        expanded = expand_component_set(components, aliases)
        added = sorted(expanded - components)
        print(json.dumps({"original": sorted(components), "expanded": sorted(expanded), "added": added}, indent=2))
        return 0

    if args.command == "list":
        aliases = load_aliases(args.aliases_file)
        groups: dict[str, list[str]] = {}
        for name, equivalents in aliases.items():
            key = ",".join(sorted(equivalents))
            if key not in groups:
                groups[key] = sorted(equivalents)
        print(json.dumps({"alias_groups": list(groups.values())}, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
