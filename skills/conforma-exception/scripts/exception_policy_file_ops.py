"""Exception policy file operations — resolution, YAML generation, and manipulation."""

from __future__ import annotations

from __future__ import annotations
import argparse
import getpass
import json
import os
import platform
import posixpath
import re
import subprocess
import sys
import tempfile
from pathlib import Path
import gitlab_ops
import konflux_environment
from exception_mr_text import build_commit_message as _build_commit_message  # noqa: F401 — backward compat re-export
from exception_mr_text import build_mr_body as _build_mr_body  # noqa: F401 — backward compat re-export
from exception_mr_text import build_mr_title as _build_mr_title  # noqa: F401 — backward compat re-export
from exception_mr_text import build_mr_title_consolidated as _build_mr_title_consolidated  # noqa: F401 — backward compat re-export
from exception_mr_text import build_commit_message_consolidated as _build_commit_message_consolidated  # noqa: F401 — backward compat re-export
from exception_mr_text import build_mr_body_consolidated as _build_mr_body_consolidated  # noqa: F401 — backward compat re-export


def _validate_repo_relative_path(path_str: str, context: str = "policy file") -> str:
    """Normalize a repo-relative path and reject any that would escape the repo root.

    Prevents path traversal via absolute paths or ``..`` segments that resolve
    outside the repository checkout directory.
    """
    normalized = posixpath.normpath(path_str)
    if normalized.startswith("/") or normalized.startswith(".."):
        raise ValueError(
            f"Unsafe {context} path {path_str!r}: "
            f"resolved to {normalized!r} which is not repo-relative"
        )
    return normalized


_KONFLUX_CLUSTER_DOMAIN = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")


_CONFORMA_POLICY_DIR = os.environ.get(
    "KONFLUX_CONFORMA_POLICY_DIR",
    f"config/{_KONFLUX_CLUSTER_DOMAIN}/product/EnterpriseContractPolicy" if _KONFLUX_CLUSTER_DOMAIN else "",
)


class AmbiguousPolicyFileError(Exception):
    """Raised when multiple policy files match and no application slug disambiguates."""

    def __init__(self, component_type: str, environment: str, candidates: list[str]):
        self.component_type = component_type
        self.environment = environment
        self.candidates = candidates
        super().__init__(
            f"Multiple policy files match {component_type}-*-{environment}.yaml: "
            f"{', '.join(candidates)}. "
            f"Set KONFLUX_APPLICATION_SLUG in ~/.conforma/.env (or via Konflux tenant env discovery) "
            f"to disambiguate, or pass --policy-file explicitly."
        )


def _get_application_slug() -> str | None:
    """Get the application slug from env (set by Konflux tenant env discovery or ~/.conforma/.env).

    The application slug identifies which set of policy files belongs to the
    current application (e.g. 'rhoai' matches registry-rhoai-prod.yaml).
    """
    return os.environ.get("KONFLUX_APPLICATION_SLUG") or None


def resolve_policy_file(component_type: str, environment: str, discovered_files: list[str] | None = None) -> str:
    """Resolve the target policy file, filtered by application slug.

    Resolution order:
      1. If KONFLUX_APPLICATION_SLUG is set, match exactly {type}-{slug}-{env}.yaml
      2. If no slug, match {type}-*-{env}.yaml; raise if multiple
      3. Fall back to glob pattern if no discovered files
    """
    conforma_policy_dir = _get_conforma_policy_dir()
    if discovered_files:
        prefix = f"{component_type}-"
        suffix = f"-{environment}.yaml"
        type_env_matches = [f for f in discovered_files if f.startswith(prefix) and f.endswith(suffix)]

        app_slug = _get_application_slug()
        if app_slug:
            exact = f"{component_type}-{app_slug}-{environment}.yaml"
            if exact in type_env_matches:
                return f"{conforma_policy_dir}/{exact}"
            if type_env_matches:
                return f"{conforma_policy_dir}/{type_env_matches[0]}"

        if len(type_env_matches) == 1:
            return f"{conforma_policy_dir}/{type_env_matches[0]}"
        if len(type_env_matches) > 1:
            raise AmbiguousPolicyFileError(component_type, environment, type_env_matches)

    return f"{conforma_policy_dir}/{component_type}-*-{environment}.yaml"


def resolve_self_service_file(component_type: str, environment: str, discovered_files: list[str] | None = None) -> str:
    """Resolve a self-service exception file, filtered by application slug."""
    if discovered_files:
        prefix = f"{component_type}-"
        suffix = f"-{environment}.yaml"
        type_env_matches = [f for f in discovered_files if f.startswith(prefix) and f.endswith(suffix)]

        app_slug = _get_application_slug()
        if app_slug:
            exact = f"{component_type}-{app_slug}-{environment}.yaml"
            if exact in type_env_matches:
                return f"exceptions/{exact}"
            if type_env_matches:
                return f"exceptions/{type_env_matches[0]}"

        if len(type_env_matches) == 1:
            return f"exceptions/{type_env_matches[0]}"
        if len(type_env_matches) > 1:
            raise AmbiguousPolicyFileError(component_type, environment, type_env_matches)

    return f"exceptions/{component_type}-*-{environment}.yaml"


def _get_conforma_policy_dir() -> str:
    """Resolve Conforma policy dir at call time (env may change after import)."""
    val = os.environ.get("KONFLUX_CONFORMA_POLICY_DIR", "")
    if val:
        return val
    domain = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
    if domain:
        return f"config/{domain}/product/EnterpriseContractPolicy"
    return _CONFORMA_POLICY_DIR


def _get_discovered_ec_files() -> list[str] | None:
    """Get the list of Conforma policy files from discovery (if available)."""
    raw = os.environ.get("KONFLUX_CONFORMA_POLICY_FILES", "")
    if raw:
        return [f.strip() for f in raw.split(",") if f.strip()]
    return None


def _get_discovered_self_service_files() -> list[str] | None:
    """Get the list of self-service exception files from discovery (if available)."""
    raw = os.environ.get("KONFLUX_SELF_SERVICE_FILES", "")
    if raw:
        return [f.strip() for f in raw.split(",") if f.strip()]
    return None


def detect_component_type(components: list[str]) -> str:
    """Detect if components are FBC or registry type."""
    for comp in components:
        if "fbc" in comp.lower():
            return "fbc"
    return "registry"


def get_target_file(component_type: str, environment: str, is_self_service: bool) -> str:
    """Determine the target policy file path using discovery or pattern matching."""
    if is_self_service:
        path = resolve_self_service_file(
            component_type, environment, _get_discovered_self_service_files()
        )
    else:
        path = resolve_policy_file(
            component_type, environment, _get_discovered_ec_files()
        )
    return _validate_repo_relative_path(path)


def generate_exception_yaml(
    rule: str,
    components: list[str],
    effective_until: str,
    reference_url: str,
    rhoaieng_url: str | None,
    rhoai_version: str,
    is_self_service: bool,
    is_weekday_restriction: bool = False,
    image_ref: str | None = None,
    reference_title: str | None = None,
    spreadsheet_url: str | None = None,
) -> str:
    """Generate the YAML exception block to append.

    Components must be Konflux component names (with -vX-Y suffix), NOT container
    image names (which end in -rhel9/-ubi9). validate_inputs.py enforces this.
    """
    if is_self_service and is_weekday_restriction and image_ref:
        return f"- value: {rule}\n  imageRef: {image_ref}\n"

    if is_self_service:
        lines = [f"- value: {rule}"]
        lines.append("  componentNames:")
        for comp in components:
            lines.append(f"    - {comp}")
        if effective_until:
            lines.append(f'  effectiveUntil: "{effective_until}"')
        return "\n".join(lines) + "\n"

    indent = "          "
    lines = []
    if rhoaieng_url:
        lines.append(f"{indent}# {rhoaieng_url}")
    lines.append(f"{indent}# impacted versions: {rhoai_version}")
    if spreadsheet_url:
        lines.append(f"{indent}# spreadsheet: {spreadsheet_url}")
    lines.append(f"{indent}- value: {rule}")
    lines.append(f"{indent}  componentNames:")
    for comp in components:
        lines.append(f"{indent}    - {comp}")
    lines.append(f'{indent}  effectiveUntil: "{effective_until}"')
    if reference_title:
        lines.append(f"{indent}  reference: {reference_url}  # {reference_title}")
    else:
        lines.append(f"{indent}  reference: {reference_url}")
    return "\n".join(lines) + "\n"


def find_existing_exceptions(content: str, rule: str, indent: str = "          ") -> list[dict]:
    """Find existing exception blocks for a given rule in the policy file content.

    Returns a list of dicts with:
      - start: line index where the block starts (the `- value:` line)
      - end: line index where the block ends (exclusive)
      - has_component_names: whether the block uses componentNames
      - component_names: list of component names (empty if not used)
      - image_url: imageUrl value if present (empty string if not)
      - effective_until_line: line index of the effectiveUntil line (or None)
      - effective_until_value: current effectiveUntil value (or None)
    """
    lines = content.split("\n")
    results = []
    value_pattern = re.compile(rf"^{re.escape(indent)}- value:\s*(.+)$")
    i = 0
    while i < len(lines):
        match = value_pattern.match(lines[i])
        if match and match.group(1).strip() == rule:
            block_start = i
            block_info: dict = {
                "start": block_start,
                "end": block_start + 1,
                "has_component_names": False,
                "component_names": [],
                "image_url": "",
                "effective_until_line": None,
                "effective_until_value": None,
            }
            i += 1
            while i < len(lines):
                line = lines[i]
                if not line.strip() or value_pattern.match(line):
                    break
                if line.startswith(f"{indent}#"):
                    break
                if line.strip().startswith("- value:"):
                    break
                if "componentNames:" in line:
                    block_info["has_component_names"] = True
                    i += 1
                    while i < len(lines) and lines[i].strip().startswith("- "):
                        comp = lines[i].strip().lstrip("- ").strip()
                        block_info["component_names"].append(comp)
                        block_info["end"] = i + 1
                        i += 1
                    continue
                if "imageUrl:" in line:
                    iu_match = re.search(r'imageUrl:\s*"?([^"]+)"?', line)
                    if iu_match:
                        block_info["image_url"] = iu_match.group(1).strip()
                if "effectiveUntil:" in line:
                    block_info["effective_until_line"] = i
                    eu_match = re.search(r'effectiveUntil:\s*"?([^"]+)"?', line)
                    if eu_match:
                        block_info["effective_until_value"] = eu_match.group(1).strip()
                block_info["end"] = i + 1
                i += 1
            results.append(block_info)
        else:
            i += 1
    return results


def _update_effective_until_in_content(content: str, line_idx: int, new_effective_until: str) -> str:
    """Replace the effectiveUntil value at the given line index."""
    lines = content.split("\n")
    old_line = lines[line_idx]
    new_line = re.sub(
        r'effectiveUntil:\s*"[^"]*"',
        f'effectiveUntil: "{new_effective_until}"',
        old_line,
    )
    if new_line == old_line:
        new_line = re.sub(
            r"effectiveUntil:\s*\S+",
            f'effectiveUntil: "{new_effective_until}"',
            old_line,
        )
    lines[line_idx] = new_line
    return "\n".join(lines)


def remove_exception_from_policy_file(
    file_path: Path,
    rule: str,
    effective_until: str,
    components: list[str] | None = None,
) -> dict:
    """Remove an expired exception block and its preceding comment header.

    The block is identified by matching rule + effectiveUntil + components.
    For unscoped exceptions (no componentNames), only rule + effectiveUntil
    are needed.

    Returns:
        {"action": "removed", "detail": "...", "lines_removed": N}
        or {"action": "not_found", "detail": "..."}
    """
    content = file_path.read_text(encoding="utf-8")
    indent = "          "
    existing = find_existing_exceptions(content, rule, indent)

    target_block = None
    for block in existing:
        if block["effective_until_value"] != effective_until:
            continue
        if components and block["has_component_names"]:
            if sorted(block["component_names"]) == sorted(components):
                target_block = block
                break
        elif not components and not block["has_component_names"]:
            target_block = block
            break
        elif components and not block["has_component_names"]:
            target_block = block
            break

    if not target_block:
        return {
            "action": "not_found",
            "detail": (
                f"No matching exception block found for rule={rule}, "
                f"effectiveUntil={effective_until}, components={components}"
            ),
        }

    lines = content.split("\n")
    block_start = target_block["start"]
    block_end = target_block["end"]

    comment_start = block_start
    i = block_start - 1
    while i >= 0:
        stripped = lines[i].strip()
        if stripped.startswith("#") and lines[i].startswith(indent):
            comment_start = i
            i -= 1
        elif stripped == "":
            i -= 1
        else:
            break

    del lines[comment_start:block_end]
    while comment_start < len(lines) and lines[comment_start].strip() == "":
        del lines[comment_start]

    file_path.write_text("\n".join(lines), encoding="utf-8")
    lines_removed = block_end - comment_start
    return {
        "action": "removed",
        "detail": (
            f"Removed expired exception for {rule} "
            f"(lines {comment_start + 1}-{block_end}, effectiveUntil={effective_until})"
        ),
        "lines_removed": lines_removed,
    }


def apply_exception_to_policy_file(
    file_path: Path,
    yaml_block: str,
    is_self_service: bool,
    rule: str,
    components: list[str],
    effective_until: str,
) -> dict:
    """Apply exception to the policy file with deduplication logic.

    Returns a dict with:
      - action: "appended" | "extended" | "appended_new_style"
      - detail: human-readable description of what was done
    """
    content = file_path.read_text(encoding="utf-8")

    if is_self_service:
        if content.rstrip().endswith("---"):
            content = content.rstrip() + "\n"
        content += yaml_block
        file_path.write_text(content, encoding="utf-8")
        return {"action": "appended", "detail": "Appended self-service exception"}

    existing = find_existing_exceptions(content, rule)

    if not existing:
        content = content.rstrip() + "\n" + yaml_block
        file_path.write_text(content, encoding="utf-8")
        return {"action": "appended", "detail": "No existing exception for this rule; appended new block"}

    sorted_components = sorted(components)
    for exc in existing:
        if exc["has_component_names"]:
            if sorted(exc["component_names"]) == sorted_components:
                if exc["effective_until_line"] is not None:
                    content = _update_effective_until_in_content(content, exc["effective_until_line"], effective_until)
                    file_path.write_text(content, encoding="utf-8")
                    old_date = exc["effective_until_value"] or "unknown"
                    return {
                        "action": "extended",
                        "detail": (
                            f"Extended existing exception effectiveUntil from "
                            f"{old_date} to {effective_until} "
                            f"(componentNames matched)"
                        ),
                    }

    has_old_style = any(not exc["has_component_names"] for exc in existing)
    if has_old_style:
        content = content.rstrip() + "\n" + yaml_block
        file_path.write_text(content, encoding="utf-8")
        return {
            "action": "appended_new_style",
            "detail": (
                "Old-style exception (no componentNames) found for this rule; "
                "left intact and appended new componentNames-based exception"
            ),
        }

    content = content.rstrip() + "\n" + yaml_block
    file_path.write_text(content, encoding="utf-8")
    return {
        "action": "appended",
        "detail": ("Existing exception found for this rule but with different componentNames; appended new block"),
    }


def append_to_policy_file(file_path: Path, yaml_block: str, is_self_service: bool) -> None:
    """Append the exception block to the target file (deprecated interface)."""
    content = file_path.read_text(encoding="utf-8")

    if is_self_service:
        if content.rstrip().endswith("---"):
            content = content.rstrip() + "\n"
        content += yaml_block
    else:
        content = content.rstrip() + "\n" + yaml_block

    file_path.write_text(content, encoding="utf-8")

