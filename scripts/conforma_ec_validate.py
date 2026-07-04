"""conforma_ec_validate.py -- Conforma exception coverage via ec CLI (dual-mode: CLI + importable).

Uses `ec validate image` as the single source of truth for exception coverage.
All exception types (config.exclude, volatileConfig.exclude, ruleData) are
evaluated by the Conforma engine itself -- no YAML parsing or guessing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
WORK_DIR = Path(os.environ.get("CONFORMA_WORKDIR", "")) if os.environ.get("CONFORMA_WORKDIR") else Path.home() / ".conforma"
EC_BINARY_DIR = WORK_DIR / "bin"
EC_BINARY_PATH = EC_BINARY_DIR / "ec"

EC_RELEASE_BASE_URL = "https://github.com/enterprise-contract/ec-cli/releases/latest/download"
EC_BINARY_NAMES = {
    ("Linux", "x86_64"): "ec_linux_amd64",
    ("Linux", "aarch64"): "ec_linux_arm64",
    ("Darwin", "x86_64"): "ec_darwin_amd64",
    ("Darwin", "arm64"): "ec_darwin_arm64",
}

EC_VALIDATE_TIMEOUT = "30m"


class EcValidateError(Exception):
    """Hard failure from ec validate operations."""


def ensure_ec_binary() -> Path:
    """Locate or download the ec CLI binary.

    Checks PATH first, then ~/.conforma/bin/ec.  Downloads from GitHub releases
    if not found.  Hard-fails if download fails.

    Returns the path to a working ec binary.
    """
    for candidate in _find_ec_candidates():
        if _verify_ec_binary(candidate):
            return candidate

    return _download_ec_binary()


def _find_ec_candidates() -> list[Path]:
    """Return candidate ec binary paths in priority order."""
    import shutil

    candidates: list[Path] = []
    path_ec = shutil.which("ec")
    if path_ec:
        candidates.append(Path(path_ec))
    if EC_BINARY_PATH.exists():
        candidates.append(EC_BINARY_PATH)
    return candidates


def _verify_ec_binary(path: Path) -> bool:
    """Check that the binary at path is a working ec CLI."""
    try:
        result = subprocess.run(
            [str(path), "version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and "Version" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def _download_ec_binary() -> Path:
    """Download ec CLI binary from GitHub releases into ~/.conforma/bin/.

    Hard-fails with EcValidateError if download fails.
    """
    system = platform.system()
    machine = platform.machine()
    key = (system, machine)

    if key not in EC_BINARY_NAMES:
        raise EcValidateError(
            f"No ec binary available for {system}/{machine}. "
            f"Supported: {', '.join(f'{s}/{m}' for s, m in EC_BINARY_NAMES)}"
        )

    binary_name = EC_BINARY_NAMES[key]
    url = f"{EC_RELEASE_BASE_URL}/{binary_name}"

    EC_BINARY_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import urllib.request

        print(f"Downloading ec CLI from {url}...", file=sys.stderr, flush=True)
        urllib.request.urlretrieve(url, str(EC_BINARY_PATH))
        EC_BINARY_PATH.chmod(EC_BINARY_PATH.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except Exception as exc:
        raise EcValidateError(
            f"Failed to download ec CLI from {url}: {exc}. "
            f"Install manually: download from {EC_RELEASE_BASE_URL} and place in PATH."
        ) from exc

    if not _verify_ec_binary(EC_BINARY_PATH):
        raise EcValidateError(
            f"Downloaded ec binary at {EC_BINARY_PATH} does not work. "
            f"Try downloading manually from {EC_RELEASE_BASE_URL}."
        )

    print(f"ec CLI installed at {EC_BINARY_PATH}", file=sys.stderr, flush=True)
    return EC_BINARY_PATH


def build_snapshot_from_entries(
    entries: list[dict], output_path: str,
) -> Path:
    """Write an ApplicationSnapshot spec.json from pre-built entries.

    Each entry must have ``name`` and ``containerImage`` keys.
    No deduplication is performed — the caller is responsible.

    Returns the path to the written spec.json.
    """
    if not entries:
        raise EcValidateError("No entries provided for snapshot")
    spec = {"components": entries}
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return out


def build_snapshot_from_csv(
    csv_path: str, output_path: str,
) -> tuple[Path, list[dict]]:
    """Construct an ApplicationSnapshot spec.json from a CSV report.

    Reads component_name and image columns, deduplicates by image digest,
    and writes a JSON file suitable for ``ec validate image --images``.

    Returns ``(path_to_spec, entries)`` where *entries* is the deduplicated
    list of ``{"name": ..., "containerImage": ...}`` dicts.
    """
    seen_digests: set[str] = set()
    components: list[dict] = []

    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            image = row.get("image", "")
            component_name = row.get("component_name", "")
            if not image or not component_name:
                continue
            digest = image.split("@")[-1] if "@" in image else image
            if digest in seen_digests:
                continue
            seen_digests.add(digest)
            components.append({
                "name": component_name,
                "containerImage": image,
            })

    if not components:
        raise EcValidateError(
            f"No valid component/image pairs found in {csv_path}. "
            f"CSV must have 'component_name' and 'image' columns."
        )

    out = build_snapshot_from_entries(components, output_path)
    return out, components


def group_entries_by_base_image(
    entries: list[dict],
) -> dict[str, list[dict]]:
    """Group snapshot entries by base image URL (everything before ``@``).

    Returns ``{base_image_url: [entries]}`` preserving insertion order.
    """
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        image = entry.get("containerImage", "")
        base = image.split("@")[0] if "@" in image else image
        groups.setdefault(base, []).append(entry)
    return groups


def prepare_policy_for_local_use(policy_path: str, output_path: str) -> Path:
    """Patch a policy YAML for local ec usage (no cluster access).

    Replaces `publicKey: 'k8s://...'` with a dummy identity block so
    --skip-image-sig-check and --skip-att-sig-check work without
    Kubernetes API access.

    Returns the path to the patched policy file.
    """
    with open(policy_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    spec = doc.get("spec", {})
    public_key = spec.get("publicKey", "")

    if public_key.startswith("k8s://"):
        del spec["publicKey"]
        if "identity" not in spec:
            spec["identity"] = {
                "issuer": "https://token.actions.githubusercontent.com",
                "subject": "https://github.com/local-validation",
            }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(doc, f, default_flow_style=False, sort_keys=False)
    return out


def run_ec_validate(
    ec_binary: Path,
    spec_json: str,
    policy_file: str,
    output_dir: str,
    timeout: str = EC_VALIDATE_TIMEOUT,
) -> dict:
    """Run `ec validate image` and return parsed violations.

    Writes ec-violations.json to output_dir.
    Hard-fails on ec binary errors.
    Returns dict with components and their violations.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    violations_path = out_dir / "ec-violations.json"

    cmd = [
        str(ec_binary), "validate", "image",
        "--images", str(spec_json),
        "--policy", str(policy_file),
        "--ignore-rekor",
        "--skip-image-sig-check",
        "--skip-att-sig-check",
        "--show-successes",
        "--output", f"json={violations_path}",
        "--timeout", timeout,
    ]

    print(f"Running: {' '.join(cmd)}", file=sys.stderr, flush=True)

    result = subprocess.run(
        cmd,
        capture_output=True, text=True,
        timeout=int(timeout.rstrip("m")) * 60 + 60,
    )

    if not violations_path.exists():
        raise EcValidateError(
            f"ec validate image did not produce output at {violations_path}.\n"
            f"stderr: {result.stderr}\n"
            f"exit code: {result.returncode}"
        )

    with open(violations_path, encoding="utf-8") as f:
        data = json.load(f)

    return data


def extract_ec_violations(ec_output: dict) -> dict[str, set[str]]:
    """Extract violation codes per component from ec validate output.

    Returns {component_name: {violation_code, ...}}.
    Component names in ec output include architecture suffixes that
    we strip for matching against CSV component names.
    """
    result: dict[str, set[str]] = {}
    for comp in ec_output.get("components", []):
        raw_name = comp.get("name", "")
        base_name = _normalize_ec_component_name(raw_name)
        if base_name not in result:
            result[base_name] = set()
        for v in comp.get("violations", []):
            code = v.get("metadata", {}).get("code", "")
            if code:
                result[base_name].add(code)
    return result


def _normalize_ec_component_name(ec_name: str) -> str:
    """Normalize ec output component name to match CSV component_name.

    ec output names may include digest/architecture suffixes like:
    'odh-dashboard-v3-5-sha256:abc123-amd64'
    CSV names are just: 'odh-dashboard-v3-5'
    """
    import re
    return re.sub(r"-sha256:[a-f0-9]+-[a-z0-9]+$", "", ec_name)


def extract_ec_successes(ec_output: dict) -> dict[str, set[str]]:
    """Extract success codes per component from ec validate output.

    Returns {component_name: {violation_code, ...}} for rules that passed
    (including because of exceptions).  Requires --show-successes flag.
    """
    result: dict[str, set[str]] = {}
    for comp in ec_output.get("components", []):
        raw_name = comp.get("name", "")
        base_name = _normalize_ec_component_name(raw_name)
        if base_name not in result:
            result[base_name] = set()
        for s in comp.get("successes", []):
            code = s.get("metadata", {}).get("code", "")
            if code:
                result[base_name].add(code)
    return result


def validate_ec_against_csv(
    csv_violations: dict[str, set[str]],
    ec_violations: dict[str, set[str]],
    ec_successes: dict[str, set[str]],
) -> dict:
    """Validate that ec evaluates every rule the CSV mentions.

    For each (component, violation_code) in CSV, exactly one of three
    outcomes is expected:
      - ec reports it as a violation (still active, no exception)
      - ec reports it as a success (exception covers it)
      - ec says nothing (divergence — rule not evaluated)

    Returns validation summary with any divergences.
    """
    confirmed_violations = 0
    confirmed_covered = 0
    divergences: list[dict] = []

    for comp, csv_codes in sorted(csv_violations.items()):
        ec_viols = ec_violations.get(comp, set())
        ec_succ = ec_successes.get(comp, set())
        for code in sorted(csv_codes):
            if code in ec_viols:
                confirmed_violations += 1
            elif code in ec_succ:
                confirmed_covered += 1
            else:
                divergences.append({
                    "component": comp,
                    "violation_code": code,
                    "reason": (
                        "The source CSV report lists this as a violation, but "
                        "running Conforma now does not evaluate this rule for "
                        "this component. The Conforma policy may have changed "
                        "since the report was generated (rule renamed, removed "
                        "from the policy bundle, or evaluation error). Coverage "
                        "cannot be verified automatically."
                    ),
                })

    total = sum(len(v) for v in csv_violations.values())
    return {
        "validated": len(divergences) == 0,
        "total_csv_violations": total,
        "confirmed_violations": confirmed_violations,
        "confirmed_covered": confirmed_covered,
        "divergence_count": len(divergences),
        "divergences": divergences,
    }


def extract_csv_violations(csv_path: str) -> dict[str, set[str]]:
    """Extract violation codes per component from CSV report.

    Returns {component_name: {violation_code, ...}}.
    """
    result: dict[str, set[str]] = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("type") != "violation":
                continue
            comp = row.get("component_name", "")
            code = row.get("code", "")
            if comp and code:
                result.setdefault(comp, set()).add(code)
    return result


def compare_coverage(
    csv_violations: dict[str, set[str]],
    ec_violations: dict[str, set[str]],
    ec_successes: dict[str, set[str]] | None = None,
) -> dict:
    """Compare CSV violations against ec validate output.

    Three-way classification when ec_successes is provided:
      - In ec_successes → covered (confirmed by Conforma engine)
      - In ec_violations → uncovered (confirmed active)
      - In neither → divergent (treated as uncovered, flagged)

    Falls back to two-way (violations only) when ec_successes is None.

    Returns structured coverage result.
    """
    covered: list[dict] = []
    uncovered: list[dict] = []
    divergent: list[dict] = []

    for comp, csv_codes in sorted(csv_violations.items()):
        ec_viols = ec_violations.get(comp, set())
        ec_succ = ec_successes.get(comp, set()) if ec_successes is not None else None
        for code in sorted(csv_codes):
            entry = {"component": comp, "violation_code": code}
            if code in ec_viols:
                uncovered.append(entry)
            elif ec_succ is not None and code in ec_succ:
                covered.append(entry)
            elif ec_succ is not None:
                entry["divergent"] = True
                uncovered.append(entry)
                divergent.append(entry)
            else:
                covered.append(entry)

    result = {
        "coverage_source": "ec_validate_image",
        "total_csv_violations": sum(len(v) for v in csv_violations.values()),
        "covered_count": len(covered),
        "uncovered_count": len(uncovered),
        "covered": covered,
        "uncovered": uncovered,
    }
    if divergent:
        result["divergent_count"] = len(divergent)
        result["divergent"] = divergent
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Conforma exception coverage via ec CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser(
        "build-snapshot",
        help="Build ApplicationSnapshot spec.json from CSV report",
    )
    p_snap.add_argument("--csv", required=True, help="Path to CSV report")
    p_snap.add_argument("--output", required=True, help="Output spec.json path")

    p_validate = sub.add_parser(
        "validate",
        help="Run ec validate image against policy",
    )
    p_validate.add_argument("--csv", required=True, help="Path to CSV report")
    p_validate.add_argument("--policy", required=True, help="Path to policy YAML")
    p_validate.add_argument(
        "--output-dir", required=True,
        help="Directory for output files (spec.json, ec-violations.json)",
    )
    p_validate.add_argument("--timeout", default=EC_VALIDATE_TIMEOUT)

    p_compare = sub.add_parser(
        "compare",
        help="Compare CSV violations against ec output",
    )
    p_compare.add_argument("--csv", required=True)
    p_compare.add_argument("--ec-output", required=True, help="Path to ec-violations.json")

    args = parser.parse_args()

    if args.command == "build-snapshot":
        path, _entries = build_snapshot_from_csv(args.csv, args.output)
        print(json.dumps({"snapshot_path": str(path)}))
        return 0

    if args.command == "validate":
        ec_bin = ensure_ec_binary()
        out_dir = Path(args.output_dir)

        spec_path, _entries = build_snapshot_from_csv(args.csv, str(out_dir / "spec.json"))
        policy_path = prepare_policy_for_local_use(
            args.policy, str(out_dir / "policy-local.yaml")
        )
        ec_output = run_ec_validate(
            ec_bin, str(spec_path), str(policy_path), str(out_dir),
            timeout=args.timeout,
        )

        csv_viols = extract_csv_violations(args.csv)
        ec_viols = extract_ec_violations(ec_output)
        ec_succ = extract_ec_successes(ec_output)

        validation = validate_ec_against_csv(csv_viols, ec_viols, ec_succ)
        result = compare_coverage(csv_viols, ec_viols, ec_succ)
        result["validation"] = validation

        print(json.dumps(result, indent=2))
        return 0

    if args.command == "compare":
        csv_viols = extract_csv_violations(args.csv)
        with open(args.ec_output, encoding="utf-8") as f:
            ec_output = json.load(f)
        ec_viols = extract_ec_violations(ec_output)
        ec_succ = extract_ec_successes(ec_output)
        result = compare_coverage(csv_viols, ec_viols, ec_succ)
        print(json.dumps(result, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
