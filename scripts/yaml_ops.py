"""yaml_ops.py -- YAML primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def _make_yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.default_flow_style = False
    return yaml


def _to_plain(value: Any) -> Any:
    """Convert ruamel.yaml types to JSON-serializable Python types."""
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    return value


def load(path: str | Path) -> dict:
    """Load single YAML document. Returns parsed data."""
    yaml = _make_yaml()
    file_path = Path(path)
    with file_path.open(encoding="utf-8") as handle:
        data = yaml.load(handle)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping at root of {file_path}, got {type(data).__name__}")
    return _to_plain(data)


def load_multi_doc(path: str | Path) -> list[dict]:
    """Load multi-document YAML. Returns list of documents."""
    yaml = _make_yaml()
    file_path = Path(path)
    documents: list[dict] = []
    with file_path.open(encoding="utf-8") as handle:
        for document in yaml.load_all(handle):
            if document is None:
                continue
            if not isinstance(document, dict):
                raise ValueError(f"Expected mapping documents in {file_path}, got {type(document).__name__}")
            documents.append(_to_plain(document))
    return documents


def dump(data: dict, path: str | Path) -> dict:
    """Dump data to YAML file. Returns {"path": str, "written": True}."""
    yaml = _make_yaml()
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)
    return {"path": str(file_path), "written": True}


def _merge_into_ruamel(existing: Any, overlay: dict) -> Any:
    """Deep-merge plain-dict overlay into a ruamel CommentedMap, preserving comments."""
    if isinstance(existing, dict) and isinstance(overlay, dict):
        for key, value in overlay.items():
            if key in existing and isinstance(existing[key], dict) and isinstance(value, dict):
                _merge_into_ruamel(existing[key], value)
            else:
                existing[key] = copy.deepcopy(value)
        return existing
    return copy.deepcopy(overlay)


def dump_preserving_comments(data: dict, path: str | Path) -> dict:
    """Dump data to YAML file preserving comments (round-trip mode)."""
    yaml = _make_yaml()
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if file_path.exists():
        with file_path.open(encoding="utf-8") as handle:
            existing = yaml.load(handle)
        if existing is None:
            existing = {}
        if not isinstance(existing, dict):
            raise ValueError(f"Cannot preserve comments for non-mapping root in {file_path}")
        _merge_into_ruamel(existing, data)
        with file_path.open("w", encoding="utf-8") as handle:
            yaml.dump(existing, handle)
    else:
        with file_path.open("w", encoding="utf-8") as handle:
            yaml.dump(data, handle)

    return {"path": str(file_path), "written": True}


def merge(base: dict, overlay: dict) -> dict:
    """Deep merge two dicts. Returns merged result."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="YAML primitives")
    sub = parser.add_subparsers(dest="command")

    load_parser = sub.add_parser("load")
    load_parser.add_argument("--path", required=True)

    dump_parser = sub.add_parser("dump")
    dump_parser.add_argument("--path", required=True)

    merge_parser = sub.add_parser("merge")
    merge_parser.add_argument("--base", required=True)
    merge_parser.add_argument("--overlay", required=True)

    args = parser.parse_args()

    if args.command == "load":
        result = load(args.path)
    elif args.command == "dump":
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            result = {"path": args.path, "written": False, "error": f"Invalid JSON on stdin: {exc}"}
        else:
            if not isinstance(data, dict):
                result = {"path": args.path, "written": False, "error": "stdin JSON must be an object"}
            else:
                result = dump(data, args.path)
    elif args.command == "merge":
        result = merge(load(args.base), load(args.overlay))
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
