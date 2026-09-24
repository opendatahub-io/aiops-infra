"""Exception policy file operations — resolution, YAML generation, and manipulation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import posixpath
import re
import tempfile
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq
import conforma_policy_ops
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
        raise ValueError(f"Unsafe {context} path {path_str!r}: resolved to {normalized!r} which is not repo-relative")
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
        path = resolve_self_service_file(component_type, environment, _get_discovered_self_service_files())
    else:
        path = resolve_policy_file(component_type, environment, _get_discovered_ec_files())
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


def _legacy_find_existing_exceptions(content: str, rule: str, indent: str = "          ") -> list[dict]:
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
        value = match.group(1).strip() if match else ""
        if not match or not (value == rule or value.startswith(f"{rule}:")):
            i += 1
            continue

        if value == rule or value.startswith(f"{rule}:"):
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
    return results


def find_existing_exceptions(content: str, rule: str | None = None, indent: str = "          ") -> list[dict]:
    """Compatibility adapter for the shared structured exception matcher."""
    del indent  # Retained for callers; YAML structure makes indentation irrelevant.
    normalized = conforma_policy_ops.find_existing_exceptions(content, rule)
    return [
        {
            **entry,
            "has_component_names": entry["has_component_names"],
            "component_names": entry["component_names"],
            "image_url": entry.get("image_url") or "",
            "effective_until_value": entry.get("effective_until_value"),
        }
        for entry in normalized
    ]


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

    # All structured policy writes use the shared YAML matcher and the
    # revision-pinned mutation contract.  The legacy line-oriented branch
    # below remains available for callers that need its historical result
    # wording, but is no longer used for a normal structured entry.
    block_yaml = _mutation_yaml()
    parsed_block = block_yaml.load(yaml_block)
    if isinstance(parsed_block, list) and parsed_block and isinstance(parsed_block[0], dict):
        entry = dict(parsed_block[0])
        records = _mutation_record(content, file_path, rule)
        exact = [
            record
            for record in records
            if record["value"] == str(entry.get("value", rule))
            and record["has_component_names"]
            and sorted(record["component_names"]) == sorted(components)
        ]
        if exact:
            target = exact[0]
            if entry.get("effectiveUntil") == target.get("effective_until_value"):
                return {"action": "no_change", "detail": "Matching structured exception already exists"}
            preview = preview_policy_mutation(
                file_path,
                {"operations": [{"operation": "extend", "target_fingerprint": target["entry_fingerprint"], "effective_until": effective_until}]},
            )
            applied = apply_policy_mutation(file_path, preview)
            if applied["status"] != "applied":
                return {"action": "blocked", "detail": applied.get("error", applied["status"])}
            return {"action": "extended", "detail": f"Extended existing exception to {effective_until}"}

        preview = preview_policy_mutation(
            file_path,
            {
                "operations": [
                    {
                        "operation": "add",
                        "rule": rule,
                        "components": components,
                        "entry": entry,
                    }
                ]
            },
        )
        if preview["status"] == "confirmation_required":
            return {"action": "confirmation_required", "detail": json.dumps(preview, sort_keys=True)}
        applied = apply_policy_mutation(file_path, preview)
        if applied["status"] != "applied":
            return {"action": "blocked", "detail": applied.get("error", applied["status"])}
        return {"action": "appended", "detail": "Appended structured exception using shared mutation"}

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


def _mutation_sha256(file_path: Path) -> str:
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def _mutation_yaml():
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    return yaml


def _path_parent(document, path: list[str | int]):
    node = document
    for part in path:
        node = node[part]
    return node


def _entry_for_record(document, record: dict):
    path = record["policy_path"]
    parent = _path_parent(document, path[:-1])
    return parent, path[-1], parent[path[-1]]


def _mutation_record(content: str, file_path: Path, rule: str | None = None) -> list[dict]:
    return conforma_policy_ops.find_existing_exceptions(content, rule, source_file=str(file_path))


def _request_value(operation: dict) -> str | None:
    entry = operation.get("entry") or {}
    return operation.get("value") or entry.get("value") or operation.get("rule")


def _record_matches_operation(record: dict, operation: dict) -> bool:
    fingerprint = operation.get("target_fingerprint") or operation.get("entry_fingerprint")
    if fingerprint and record["entry_fingerprint"] != fingerprint:
        return False
    value = _request_value(operation)
    if value and not conforma_policy_ops.exception_value_matches(record["value"], value):
        return False
    components = operation.get("components")
    if components is not None:
        operation_type = operation.get("operation", operation.get("action", "add"))
        if operation_type == "remove" and set(components).issubset(set(record["component_names"])):
            return True
        if sorted(record["component_names"]) != sorted(components):
            return False
    return True


def _action(action: str, record: dict | None = None, **fields) -> dict:
    result = {"action": action, **fields}
    if record:
        result.update(
            {
                "target_fingerprint": record["entry_fingerprint"],
                "policy_path": record["policy_path"],
                "value": record["value"],
                "before": {key: record.get(key) for key in (
                    "value", "component_names", "effective_until_value", "reference", "image_url", "image_ref"
                )},
            }
        )
    return result


def _preview_choice(decision_id: str, target: dict, request: dict) -> dict:
    components = request.get("components") or []
    return {
        "decision_id": decision_id,
        "target_fingerprints": [target["entry_fingerprint"]],
        "choices": [
            {
                "choice_id": "keep_broader",
                "label": "Keep the broader exception",
                "description": "Leave the existing broader exception unchanged and do not add a scoped mutation.",
                "actions": [],
                "before": [target],
                "after": [target],
            },
            {
                "choice_id": "add_scoped",
                "label": "Add a component-scoped exception",
                "description": (
                    f"Add an exception only for {', '.join(components)} and leave the broader exception untouched."
                ),
                "actions": [_action("add", entry=request.get("entry") or {
                    "value": request.get("value") or target["value"],
                    "componentNames": components,
                    "effectiveUntil": request.get("effective_until"),
                })],
                "before": [target],
                "after": [request.get("entry") or {}],
            },
        ],
    }


def preview_policy_mutation(file_path: str | Path, request: dict) -> dict:
    """Build a revision-pinned, user-reviewable policy mutation preview."""
    path = Path(file_path)
    try:
        content = path.read_text(encoding="utf-8")
        records = _mutation_record(content, path)
    except (OSError, ValueError) as exc:
        return {
            "status": "error",
            "file_path": str(path),
            "file_sha256": "",
            "unconditional_actions": [],
            "decisions": [],
            "error": str(exc),
        }

    unconditional: list[dict] = []
    decisions: list[dict] = []
    for index, operation in enumerate(request.get("operations", []), start=1):
        operation_type = operation.get("operation", operation.get("action", "add"))
        matches = [record for record in records if _record_matches_operation(record, operation)]
        if operation_type == "add":
            broader = [record for record in records if record["base_rule"] == (operation.get("rule") or "").split(":", 1)[0]
                       and not record["has_component_names"]]
            if broader and operation.get("components"):
                decisions.append(_preview_choice(f"decision-{index}", broader[0], operation))
            else:
                unconditional.append(_action("add", entry=operation.get("entry") or {
                    "value": _request_value(operation),
                    "componentNames": operation.get("components", []),
                    "effectiveUntil": operation.get("effective_until"),
                }))
            continue
        if len(matches) != 1:
            return {
                "status": "blocked",
                "file_path": str(path),
                "file_sha256": _mutation_sha256(path),
                "unconditional_actions": [],
                "decisions": [],
                "error": f"Expected one mutation target for operation {index}, found {len(matches)}",
            }
        target = matches[0]
        if operation_type == "extend":
            unconditional.append(_action("replace", target, effective_until=operation["effective_until"]))
        elif operation_type == "remove":
            if operation.get("components") and target["has_component_names"]:
                unconditional.append(_action("remove_components", target, components=operation["components"]))
            elif operation.get("components") and not target["has_component_names"]:
                decisions.append(_preview_choice(f"decision-{index}", target, operation))
            else:
                unconditional.append(_action("remove", target))
        else:
            return {
                "status": "error", "file_path": str(path), "file_sha256": _mutation_sha256(path),
                "unconditional_actions": [], "decisions": [], "error": f"Unsupported mutation operation: {operation_type}",
            }

    return {
        "status": "confirmation_required" if decisions else "ready",
        "file_path": str(path),
        "file_sha256": _mutation_sha256(path),
        "unconditional_actions": unconditional,
        "decisions": decisions,
        "error": None,
    }


def _apply_action(document, action: dict) -> None:
    operation = action["action"]
    if operation == "add":
        entry = copy.deepcopy(action["entry"])
        if not entry.get("value"):
            raise ValueError("Cannot add a policy exception without value")
        # Add to the first supported exception sequence, or create the historical path.
        sequences = list(conforma_policy_ops._iter_exception_sequences(document))
        if not sequences:
            def create_sequence(node):
                if not isinstance(node, dict):
                    return None
                for key, value in node.items():
                    if str(key) in {"volatileCriteria", "exclude"} and value is None:
                        node[key] = CommentedSeq()
                        return node[key]
                    if isinstance(value, dict):
                        created = create_sequence(value)
                        if created is not None:
                            return created
                return None

            created = create_sequence(document)
            if created is None:
                raise ValueError("Policy contains no supported exception sequence")
            created.append(entry)
            return
        sequences[0][2].append(entry)
        return
    parent, index, entry = _entry_for_record(document, action)
    if operation == "remove":
        del parent[index]
    elif operation == "replace":
        entry["effectiveUntil"] = action["effective_until"]
    elif operation == "remove_components":
        if "componentNames" not in entry:
            raise ValueError("Cannot remove components from an unscoped exception")
        remaining = [name for name in entry["componentNames"] if name not in action["components"]]
        if remaining:
            entry["componentNames"] = remaining
        else:
            del parent[index]
    else:
        raise ValueError(f"Unsupported policy action: {operation}")


def apply_policy_mutation(
    file_path: str | Path,
    preview: dict,
    selections: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Apply one complete preview atomically, refusing stale or incomplete input."""
    path = Path(file_path)
    selections = selections or {}
    if preview.get("status") not in {"ready", "confirmation_required"}:
        return {"status": "blocked", "changed": False, "file_path": str(path), "details": [], "error": "Preview is not applicable"}
    try:
        content = path.read_text(encoding="utf-8")
        if _mutation_sha256(path) != preview.get("file_sha256"):
            return {"status": "stale", "changed": False, "file_path": str(path), "details": [], "error": "Policy file changed since preview"}
        yaml = _mutation_yaml()
        document = yaml.load(content)
        current = {record["entry_fingerprint"]: record for record in _mutation_record(content, path)}
        actions = list(preview.get("unconditional_actions", []))
        for decision in preview.get("decisions", []):
            choice_id = selections.get(decision["decision_id"])
            if choice_id is None:
                return {"status": "blocked", "changed": False, "file_path": str(path), "details": [], "error": f"Missing selection for {decision['decision_id']}"}
            choices = {choice["choice_id"]: choice for choice in decision["choices"]}
            if choice_id not in choices:
                return {"status": "blocked", "changed": False, "file_path": str(path), "details": [], "error": f"Unknown selection {choice_id}"}
            actions.extend(choices[choice_id].get("actions", []))
        if not actions:
            return {"status": "no_change_required", "changed": False, "file_path": str(path), "details": [], "error": None}
        for action in actions:
            target = action.get("target_fingerprint")
            if target and target not in current:
                return {"status": "stale", "changed": False, "file_path": str(path), "details": [], "error": f"Target {target} changed since preview"}
            _apply_action(document, action)
        output = tempfile.SpooledTemporaryFile(mode="w+", encoding="utf-8")
        yaml.dump(document, output)
        output.seek(0)
        rendered = output.read()
        if dry_run:
            return {"status": "dry_run", "changed": rendered != content, "file_path": str(path), "details": actions, "error": None}
        if rendered == content:
            return {"status": "no_change_required", "changed": False, "file_path": str(path), "details": actions, "error": None}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary.write(rendered)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        return {"status": "applied", "changed": True, "file_path": str(path), "details": actions, "error": None}
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "error", "changed": False, "file_path": str(path), "details": [], "error": str(exc)}
