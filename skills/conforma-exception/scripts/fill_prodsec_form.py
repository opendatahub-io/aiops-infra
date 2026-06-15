#!/usr/bin/env python3
"""Generate Google Form pre-fill URLs for ProdSec exception requests.

Modes:
  --discover <saved_form.html>   Parse saved form HTML to auto-generate
                                 prodsec_form_config.yaml with entry IDs.

  --generate                     Read config YAML + exception data flags,
                                 produce a pre-fill URL for user review.

  --validate-config              Check config YAML health (staleness, missing
                                 required mappings) and exit.

  --dry-run                      (with --generate) Print URL without opening.

Dependencies: Python standard library only (json, re, urllib.parse, yaml).
YAML is the only non-stdlib dep and is already required by the project.

Usage:
  # Discover form fields from saved HTML page source
  python3 fill_prodsec_form.py --discover /path/to/saved_form.html

  # Generate a pre-fill URL
  python3 fill_prodsec_form.py --generate \\
    --rule hermetic_task.hermetic \\
    --components "odh-mlflow-v3-3" \\
    --rhoai-version rhoai-3.3 \\
    --effective-until 2026-10-03 \\
    --exception-scope "Non-hermetic build for odh-mlflow" \\
    --exception-risk "Low risk: dev-preview component" \\
    --exception-remediation "Will be fixed in next release" \\
    --exception-impact "Blocks release gate for rhoai-3.3" \\
    --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-12345
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG_PATH = _SCRIPT_DIR / "prodsec_form_config.yaml"

STALENESS_WARN_DAYS = 180


# ---------------------------------------------------------------------------
# Discover mode: parse FB_PUBLIC_LOAD_DATA_ from saved HTML
# ---------------------------------------------------------------------------

_FB_PATTERN = re.compile(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\])\s*;", re.DOTALL)

_FIELD_TYPE_MAP = {
    0: "short_text",
    1: "paragraph",
    2: "radio",
    3: "dropdown",
    4: "checkboxes",
    5: "scale",
    7: "grid",
    9: "date",
    10: "time",
}


def _extract_fb_data(html: str) -> list:
    """Extract the FB_PUBLIC_LOAD_DATA_ JSON array from Google Forms HTML."""
    match = _FB_PATTERN.search(html)
    if not match:
        raise ValueError(
            "Could not find FB_PUBLIC_LOAD_DATA_ in the HTML. "
            "Make sure you saved the full page source (Ctrl+U or View Page Source), "
            "not the rendered DOM from DevTools."
        )
    raw = match.group(1)
    return json.loads(raw)


def _parse_form_fields(fb_data: list) -> tuple[str, list[dict]]:
    """Parse form title and fields from the FB_PUBLIC_LOAD_DATA_ structure.

    Returns (form_title, fields) where each field is a dict with:
      - entry_id: str (the Google Forms entry.XXXXXXX ID)
      - question: str (the question text)
      - field_type: str (human-readable type name)
      - required: bool
      - options: list[str] | None (for radio/dropdown/checkboxes)
    """
    form_title = fb_data[3] if len(fb_data) > 3 else "Unknown Form"

    fields = []
    field_groups = fb_data[1][1] if len(fb_data) > 1 and fb_data[1] else []

    for group in field_groups:
        if not isinstance(group, list) or len(group) < 2:
            continue

        question_text = group[1] if group[1] else "(no title)"

        if not group[4]:
            continue

        for field_detail in group[4]:
            if not isinstance(field_detail, list):
                continue

            entry_id = str(field_detail[0])
            raw_type = field_detail[3] if len(field_detail) > 3 else -1
            field_type = _FIELD_TYPE_MAP.get(raw_type, f"unknown({raw_type})")
            required = bool(field_detail[4][0][2]) if (
                len(field_detail) > 4 and field_detail[4]
                and field_detail[4][0] and len(field_detail[4][0]) > 2
            ) else False

            options = None
            if field_detail[1] and isinstance(field_detail[1], list):
                options = [
                    opt[0] for opt in field_detail[1]
                    if isinstance(opt, list) and opt
                ]

            fields.append({
                "entry_id": entry_id,
                "question": question_text,
                "field_type": field_type,
                "required": required,
                "options": options,
            })

    return form_title, fields


def discover(html_path: Path) -> dict:
    """Parse a saved Google Form HTML file and return config dict.

    The returned dict is ready to be written as prodsec_form_config.yaml.
    """
    html = html_path.read_text(encoding="utf-8", errors="replace")
    fb_data = _extract_fb_data(html)
    form_title, fields = _parse_form_fields(fb_data)

    config: dict = {
        "form_title": form_title,
        "discovered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "field_count": len(fields),
        "fields": [],
        "field_mapping": {},
    }

    for f in fields:
        entry: dict = {
            "entry_id": f["entry_id"],
            "question": f["question"],
            "field_type": f["field_type"],
            "required": f["required"],
        }
        if f["options"]:
            entry["options"] = f["options"]
        config["fields"].append(entry)
        config["field_mapping"][f"entry_{f['entry_id']}"] = None

    return config


def write_config(config: dict, output_path: Path) -> None:
    """Write the discovered config to YAML."""
    if yaml is None:
        raise ImportError("PyYAML is required. Install with: pip install pyyaml")

    with open(output_path, "w") as fh:
        fh.write("# Auto-generated by fill_prodsec_form.py --discover\n")
        fh.write("# See references/update-prodsec-form.md for update instructions.\n")
        fh.write("#\n")
        fh.write("# field_mapping: maps internal exception data keys to entry IDs.\n")
        fh.write("# Set the value to the internal key name (e.g., 'rule', 'components').\n")
        fh.write("# Leave as null for fields that should not be auto-filled.\n\n")
        yaml.dump(config, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Health check / config validation
# ---------------------------------------------------------------------------

class ConfigHealthWarning:
    """A single health-check warning."""
    def __init__(self, level: str, message: str):
        self.level = level  # "warn" or "error"
        self.message = message

    def __repr__(self) -> str:
        return f"[{self.level.upper()}] {self.message}"


def validate_config(config_path: Path | None = None) -> list[ConfigHealthWarning]:
    """Check the form config YAML for staleness and completeness.

    Returns a list of warnings/errors. Empty list means healthy.
    """
    if yaml is None:
        return [ConfigHealthWarning("error", "PyYAML not installed")]

    path = config_path or _DEFAULT_CONFIG_PATH
    warnings: list[ConfigHealthWarning] = []

    if not path.is_file():
        warnings.append(ConfigHealthWarning(
            "error",
            f"Config file not found: {path}. "
            "Run --discover with a saved form HTML to generate it. "
            "See references/update-prodsec-form.md for instructions."
        ))
        return warnings

    with open(path) as fh:
        config = yaml.safe_load(fh)

    if not config or not isinstance(config, dict):
        warnings.append(ConfigHealthWarning("error", f"Config file is empty or malformed: {path}"))
        return warnings

    discovered_at = config.get("discovered_at")
    if discovered_at:
        try:
            ts = datetime.datetime.fromisoformat(discovered_at)
            age_days = (datetime.datetime.now(datetime.timezone.utc) - ts).days
            if age_days > STALENESS_WARN_DAYS:
                warnings.append(ConfigHealthWarning(
                    "warn",
                    f"Form config is {age_days} days old (discovered {discovered_at}). "
                    f"The ProdSec form may have changed. "
                    f"See references/update-prodsec-form.md to refresh."
                ))
        except (ValueError, TypeError):
            warnings.append(ConfigHealthWarning("warn", f"Cannot parse discovered_at: {discovered_at}"))

    field_mapping = config.get("field_mapping", {})
    mapped_count = sum(1 for v in field_mapping.values() if v is not None)
    if mapped_count == 0:
        warnings.append(ConfigHealthWarning(
            "error",
            "No fields are mapped in field_mapping. "
            "Edit prodsec_form_config.yaml to map entry IDs to exception data keys."
        ))

    required_fields = [
        f for f in config.get("fields", []) if f.get("required")
    ]
    mapped_entry_ids = {
        k.replace("entry_", "") for k, v in field_mapping.items() if v is not None
    }
    unmapped_required = [
        f for f in required_fields if f["entry_id"] not in mapped_entry_ids
    ]
    if unmapped_required:
        names = ", ".join(f'"{f["question"]}"' for f in unmapped_required)
        warnings.append(ConfigHealthWarning(
            "warn",
            f"Required form fields not mapped: {names}. "
            f"These will be empty in the pre-fill URL and the user must fill them manually."
        ))

    return warnings


# ---------------------------------------------------------------------------
# Generate mode: build pre-fill URL
# ---------------------------------------------------------------------------

_KNOWN_DATA_KEYS = {
    "rule", "components", "rhoai_version", "effective_until",
    "exception_scope", "exception_risk", "exception_remediation",
    "exception_impact", "rhoaieng_url", "vendor_tag",
    "summary_context", "authorized_party",
}


def _load_config(config_path: Path | None = None) -> dict:
    """Load and return the form config YAML."""
    if yaml is None:
        raise ImportError("PyYAML is required")
    path = config_path or _DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"Config file not found: {path}. "
            "Run --discover first. See references/update-prodsec-form.md."
        )
    with open(path) as fh:
        return yaml.safe_load(fh)


def generate_prefill_url(
    config_path: Path | None = None,
    *,
    rule: str = "",
    components: str = "",
    rhoai_version: str = "",
    effective_until: str = "",
    exception_scope: str = "",
    exception_risk: str = "",
    exception_remediation: str = "",
    exception_impact: str = "",
    rhoaieng_url: str = "",
    vendor_tag: str = "",
    summary_context: str = "",
    authorized_party: str = "",
) -> str:
    """Build a Google Forms pre-fill URL from exception data.

    Returns the full URL string. The caller is responsible for presenting
    it to the user.
    """
    config = _load_config(config_path)

    base_url = config.get("form_url")
    if not base_url:
        form_id = config.get("form_id")
        if form_id:
            base_url = f"https://docs.google.com/forms/d/e/{form_id}/viewform"
        else:
            raise ValueError(
                "Config must contain 'form_url' or 'form_id'. "
                "Add the form URL to prodsec_form_config.yaml."
            )

    data_values = {
        "rule": rule,
        "components": components,
        "rhoai_version": rhoai_version,
        "effective_until": effective_until,
        "exception_scope": exception_scope,
        "exception_risk": exception_risk,
        "exception_remediation": exception_remediation,
        "exception_impact": exception_impact,
        "rhoaieng_url": rhoaieng_url,
        "vendor_tag": vendor_tag,
        "summary_context": summary_context,
        "authorized_party": authorized_party,
    }

    field_mapping = config.get("field_mapping", {})
    fields_by_id = {f["entry_id"]: f for f in config.get("fields", [])}

    params: list[tuple[str, str]] = []

    for mapping_key, data_key in field_mapping.items():
        if data_key is None:
            continue

        entry_id = mapping_key.replace("entry_", "")
        value = data_values.get(data_key, "")

        if not value:
            continue

        field_info = fields_by_id.get(entry_id, {})
        field_type = field_info.get("field_type", "short_text")

        if field_type in ("radio", "dropdown"):
            options = field_info.get("options", [])
            matched = _match_option(value, options)
            if matched:
                value = matched

        params.append((f"entry.{entry_id}", value))

    if not params:
        return base_url

    separator = "&" if "?" in base_url else "?"
    query = urlencode(params, quote_via=quote)
    return f"{base_url}{separator}{query}"


def _match_option(value: str, options: list[str]) -> str | None:
    """Try to match a value to a predefined option (case-insensitive)."""
    value_lower = value.strip().lower()
    for opt in options:
        if opt.strip().lower() == value_lower:
            return opt
    for opt in options:
        if value_lower in opt.strip().lower() or opt.strip().lower() in value_lower:
            return opt
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Google Form pre-fill URLs for ProdSec exception requests.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--discover",
        metavar="HTML_FILE",
        help="Parse saved form HTML to generate prodsec_form_config.yaml.",
    )
    mode.add_argument("--generate", action="store_true", help="Generate a pre-fill URL.")
    mode.add_argument(
        "--validate-config", action="store_true",
        help="Check config health and exit.",
    )

    parser.add_argument("--config", type=Path, help="Path to form config YAML.")
    parser.add_argument("--output", type=Path, help="Output path for --discover (default: prodsec_form_config.yaml).")
    parser.add_argument("--dry-run", action="store_true", help="Print URL only, do not open.")

    gen = parser.add_argument_group("generate options")
    gen.add_argument("--rule", default="")
    gen.add_argument("--components", default="")
    gen.add_argument("--rhoai-version", default="")
    gen.add_argument("--effective-until", default="")
    gen.add_argument("--exception-scope", default="")
    gen.add_argument("--exception-risk", default="")
    gen.add_argument("--exception-remediation", default="")
    gen.add_argument("--exception-impact", default="")
    gen.add_argument("--rhoaieng-url", default="")
    gen.add_argument("--vendor-tag", default="")
    gen.add_argument("--summary-context", default="")
    gen.add_argument("--authorized-party", default="")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.discover:
        html_path = Path(args.discover)
        if not html_path.is_file():
            print(f"ERROR: File not found: {html_path}", file=sys.stderr)
            return 1

        config = discover(html_path)
        output_path = args.output or _DEFAULT_CONFIG_PATH
        write_config(config, output_path)
        print(f"Discovered {config['field_count']} form fields.")
        print(f"Config written to: {output_path}")
        print()
        print("Next steps:")
        print("  1. Open the config file and map entry IDs to exception data keys")
        print("  2. Add 'form_url' or 'form_id' to the config")
        print("  3. Run --validate-config to verify the mapping")
        return 0

    if args.validate_config:
        warnings = validate_config(args.config)
        if not warnings:
            print("Config is healthy.")
            return 0
        for w in warnings:
            print(str(w), file=sys.stderr)
        has_errors = any(w.level == "error" for w in warnings)
        return 1 if has_errors else 0

    if args.generate:
        warnings = validate_config(args.config)
        for w in warnings:
            print(str(w), file=sys.stderr)
        if any(w.level == "error" for w in warnings):
            return 1

        url = generate_prefill_url(
            config_path=args.config,
            rule=args.rule,
            components=args.components,
            rhoai_version=args.rhoai_version,
            effective_until=args.effective_until,
            exception_scope=args.exception_scope,
            exception_risk=args.exception_risk,
            exception_remediation=args.exception_remediation,
            exception_impact=args.exception_impact,
            rhoaieng_url=args.rhoaieng_url,
            vendor_tag=args.vendor_tag,
            summary_context=args.summary_context,
            authorized_party=args.authorized_party,
        )
        print(url)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
