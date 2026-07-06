"""YAML quoting utilities shared across conforma scripts."""

from __future__ import annotations

import re

import yaml


class QuotedStr(str):
    """String subclass that forces YAML double-quoting."""


def quoted_str_representer(dumper: yaml.Dumper, data: QuotedStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


def safe_yaml_dump(data: dict, comment_header: str = "") -> str:
    """Dump data to YAML with defensive quoting for timestamps, rule codes, URLs.

    All string values that could be misinterpreted by YAML (timestamps,
    strings containing colons, URLs) are explicitly double-quoted.
    """
    safe_data = quote_strings_recursively(data)

    dumper = yaml.Dumper
    dumper.add_representer(QuotedStr, quoted_str_representer)

    body = yaml.dump(
        safe_data,
        Dumper=dumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )

    if comment_header:
        return comment_header.rstrip("\n") + "\n\n" + body
    return body


def needs_quoting(value: str) -> bool:
    """Determine if a string needs explicit quoting in YAML."""
    if not value:
        return False
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return True
    if ":" in value:
        return True
    if value.startswith("http://") or value.startswith("https://"):
        return True
    if value.startswith("#"):
        return True
    if value.lower() in ("true", "false", "yes", "no", "null", "on", "off"):
        return True
    return False


def quote_strings_recursively(obj):
    """Walk a data structure and wrap strings that need quoting."""
    if isinstance(obj, str):
        if needs_quoting(obj):
            return QuotedStr(obj)
        return obj
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            safe_key = QuotedStr(k) if isinstance(k, str) and needs_quoting(k) else k
            result[safe_key] = quote_strings_recursively(v)
        return result
    if isinstance(obj, list):
        return [quote_strings_recursively(item) for item in obj]
    return obj


