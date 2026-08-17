"""File and directory operations: copy tenant dir, rename files, update versions, RPA files."""

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from constants import (
    BUILD_MANIFESTS_SCRIPT,
    RPA_PRODUCT_BASE,
    RPA_SERVICE_BASE,
    TENANT_BASE,
    TENANTS_CONFIG_DIR,
    TENANT_KUSTOMIZATION,
)
from util import apply_version_replacements, base_minor_version

logger = logging.getLogger(__name__)


class _KustomizationDumper(yaml.SafeDumper):
    """Indent list items under mapping keys (yamllint indentation + kustomize style)."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def copy_version_directory(
    repo_path: Path,
    tenant_base: str,
    previous_minor_dir: str,
    new_minor_dir: str,
) -> Path:
    """
    Copy the previous minor release directory to the new minor directory.
    Returns path to the new directory.
    """
    src = repo_path / tenant_base / previous_minor_dir
    dst = repo_path / tenant_base / new_minor_dir
    if not src.is_dir():
        raise FileNotFoundError(f"Previous minor directory not found: {src}")

    if dst.exists():
        logger.info("Destination directory already exists, skipping copy: %s", dst)
        return dst

    logger.info("Copying %s -> %s", src, dst)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    logger.info("Created new tenant directory: %s", dst)
    return dst


def rename_files(
    directory: Path,
    previous_minor_dir: str,
    new_minor_dir: str,
) -> None:
    """
    Rename versioned files inside the directory.
    e.g. ProdReleasePlans-v2.18.yaml -> ProdReleasePlans-v2.19.yaml
    """
    if previous_minor_dir == new_minor_dir:
        return
    for f in directory.iterdir():
        if not f.is_file():
            continue
        if previous_minor_dir in f.name:
            new_name = f.name.replace(previous_minor_dir, new_minor_dir, 1)
            new_path = f.parent / new_name
            logger.info("Renaming %s -> %s", f.name, new_name)
            f.rename(new_path)


def update_file_versions(
    directory: Path,
    previous_version: str,
    new_version: str,
    previous_version_dash: str,
    new_version_dash: str,
    previous_ea_display: Optional[str] = None,
    new_ea_display: Optional[str] = None,
) -> None:
    """
    In all files under directory, replace version refs (dotted, dashed, vX-Y, vX.Y, and EA display form).
    """
    for f in directory.rglob("*"):
        if not f.is_file():
            continue
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("Skipping %s (read error): %s", f, e)
            continue
        original = raw
        raw = apply_version_replacements(
            raw,
            previous_version,
            new_version,
            previous_version_dash,
            new_version_dash,
            previous_ea_display=previous_ea_display,
            new_ea_display=new_ea_display,
        )
        if raw != original:
            f.write_text(raw, encoding="utf-8")
            logger.info("Updated version references in %s", f.relative_to(directory.parent))


def update_kustomization(
    repo_path: Path,
    kustomization_path: str,
    new_minor_dir: str,
) -> None:
    """Add the new directory path to the resources list in tenant kustomization.yaml."""
    k_path = repo_path / kustomization_path
    if not k_path.is_file():
        raise FileNotFoundError(f"Kustomization file not found: {k_path}")
    logger.info("Updating kustomization: %s", kustomization_path)
    with open(k_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    resources = list(data.get("resources") or [])
    new_resource = new_minor_dir
    if resources:
        sample = next((r for r in resources if isinstance(r, str) and r.startswith("v")), None)
        if sample and sample.endswith("/") and not new_resource.endswith("/"):
            new_resource = new_resource + "/"
    if new_resource in resources or new_resource.rstrip("/") in {
        str(r).rstrip("/") for r in resources
    }:
        logger.info("Resource %s already in kustomization, skipping add", new_resource)
        return
    resources.append(new_resource)
    data["resources"] = resources
    with open(k_path, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(
            data,
            f,
            Dumper=_KustomizationDumper,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=1000,
        )
    logger.info("Added resource: %s", new_resource)


def create_rpa_files(
    repo_path: Path,
    rpa_base: str,
    previous_version_dash: str,
    new_version_dash: str,
    previous_version: str,
    new_version: str,
    is_ea: bool = False,
    previous_ea_display: Optional[str] = None,
    new_ea_display: Optional[str] = None,
) -> None:
    """
    Copy previous RPA files to new version: rename files and update version refs inside.
    - When is_ea is False (e.g. 3.4->3.5): only copy standard RPA files (exclude *-ea-*).
    - When is_ea is True and previous is standard (e.g. 3.4->3.5.ea.1): only copy standard
      v3-4-* files and create v3-5-ea-1-* from them; do NOT copy v3-4-ea-1 or v3-4-ea-2 (so we
      don't create 3.5.ea.2 or duplicate EA content).
    - When is_ea is True and previous is EA (e.g. 3.4.ea.1->3.5.ea.1): only copy matching
      v3-4-ea-1-* and create v3-5-ea-1-* (prefix match already ensures we don't pick ea-2).
    """
    base = repo_path / rpa_base
    if not base.is_dir():
        raise FileNotFoundError(f"RPA directory not found: {base}")
    prefix_old = f"v{previous_version_dash}"
    prefix_new = f"v{new_version_dash}"
    previous_is_ea = "-ea-" in previous_version_dash
    copied = []
    for f in base.iterdir():
        if not f.is_file():
            continue
        if prefix_old not in f.name:
            continue
        if not is_ea and (f"-ea-" in f.name or prefix_old + "-ea" in f.name):
            logger.debug("Skipping EA file (standard version requested): %s", f.name)
            continue
        if is_ea and not previous_is_ea and (f"-ea-" in f.name or prefix_old + "-ea" in f.name):
            logger.debug("Skipping other EA file (only creating %s, not ea.2 etc.): %s", prefix_new, f.name)
            continue
        new_name = f.name.replace(prefix_old, prefix_new, 1)
        dest = base / new_name
        logger.info("Copying RPA file %s -> %s", f.name, new_name)
        shutil.copy2(f, dest)
        copied.append(dest)
    # For EA new versions, product_version must be X.Y only (e.g. "3.5"), not "3.5.ea.1".
    base_ver = base_minor_version(new_version)
    fix_product_version = is_ea and base_ver != new_version

    for f in copied:
        raw = f.read_text(encoding="utf-8", errors="replace")
        raw = apply_version_replacements(
            raw,
            previous_version,
            new_version,
            previous_version_dash,
            new_version_dash,
            previous_ea_display=previous_ea_display,
            new_ea_display=new_ea_display,
        )
        if fix_product_version:
            # Replace product_version: "3.5-ea.1" (or unquoted) -> "3.5"
            raw = re.sub(
                r'(product_version:\s*["\']?)' + re.escape(new_version) + r'(["\']?)',
                lambda m: m.group(1) + base_ver + m.group(2),
                raw,
            )
            logger.debug("Fixed product_version to %r in %s", base_ver, f.name)

        # Handle charts files: add version tags to mapping.defaults.tags for Y stream (non-EA)
        is_charts_file = "charts-prod.yaml" in f.name or "charts-stage.yaml" in f.name
        # Check only the target version (new_version), not is_ea flag (which considers both source and target)
        # This ensures EA→Y stream transitions (e.g., 3.5-ea.1 → 3.5) correctly add the tags
        target_is_ea = "-ea-" in new_version_dash
        if is_charts_file and not target_is_ea:
            # For Y stream releases, replace tags using regex to preserve YAML formatting
            # Three required tags:
            # 1. vX.Y (e.g., v3.5)
            # 2. vX.Y.0-{{ release_timestamp }} (template placeholder)
            # 3. vX.Y.0 (e.g., v3.5.0)
            version_base = new_version_dash.replace('-', '.')  # e.g., "3.5"

            # Pattern to match the tags section (preserving indentation)
            # Matches from "tags:" to just before "pushSourceContainer:"
            # This handles both 2-tag and 3-tag cases
            tags_pattern = re.compile(
                r'(        tags:\n)'  # Capture "tags:" with its indentation
                r'(          -[^\n]+\n){1,3}'  # Match 1-3 existing tag lines
                r'(?=        pushSourceContainer:)',  # Look ahead to next field
                re.MULTILINE
            )

            # Build the replacement with all three tags (quoted for YAML compatibility)
            replacement = (
                f'        tags:\n'
                f'          - "v{version_base}"\n'
                f'          - "v{version_base}.0-{{{{ release_timestamp }}}}"\n'
                f'          - "v{version_base}.0"\n'
            )

            # Replace tags section
            new_raw = tags_pattern.sub(replacement, raw)

            if new_raw != raw:
                raw = new_raw
                logger.debug("Updated tags to v%s, v%s.0-{{ release_timestamp }}, v%s.0 in %s",
                           version_base, version_base, version_base, f.name)
            else:
                logger.warning("Could not find tags pattern in %s to update", f.name)

        f.write_text(raw, encoding="utf-8")
    logger.info("Created %d RPA files under %s", len(copied), rpa_base)


def run_build_manifests(repo_path: Path) -> None:
    """Run tenants-config/build-manifests.sh to regenerate manifests (e.g. auto-generated/)."""
    tenants_config = repo_path / TENANTS_CONFIG_DIR
    script = tenants_config / BUILD_MANIFESTS_SCRIPT
    if not script.is_file():
        raise FileNotFoundError(f"Build script not found: {script}")
    logger.info("Running %s/%s", TENANTS_CONFIG_DIR, BUILD_MANIFESTS_SCRIPT)
    result = subprocess.run(
        ["./build-manifests.sh"],
        cwd=tenants_config,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"build-manifests.sh failed (exit {result.returncode})\nstderr: {result.stderr}\nstdout: {result.stdout}"
        )
    logger.info("build-manifests.sh completed successfully")


