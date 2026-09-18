"""Load and validate the C14 project-specific Jira field mapping."""

from __future__ import annotations

from pathlib import Path

import yaml_ops

MAPPING_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "conforma-analyze"
    / "references"
    / "jira-project-field-mapping.yaml"
)
REQUIRED_PROJECT_FIELDS = {
    "issue_types",
    "discovery_only",
    "target_version_fields",
    "fix_version_fields",
    "affected_version_fields",
    "component_fields",
    "closed_prior_context",
}


def load_project_mapping(path: str | Path = MAPPING_PATH) -> dict:
    """Load the mapping and fail explicitly when its contract is invalid."""
    mapping = yaml_ops.load(path)
    if not isinstance(mapping.get("mapping_version"), int):
        raise ValueError("Jira project mapping requires integer mapping_version")
    projects = mapping.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise ValueError("Jira project mapping requires a non-empty projects mapping")
    for project, config in projects.items():
        if not isinstance(config, dict):
            raise ValueError(f"Jira mapping for {project} must be a mapping")
        missing = REQUIRED_PROJECT_FIELDS - set(config)
        if missing:
            raise ValueError(f"Jira mapping for {project} missing fields: {sorted(missing)}")
    return mapping


def project_config(project: str, path: str | Path = MAPPING_PATH) -> dict:
    """Return one known project mapping; unknown projects are hard errors."""
    projects = load_project_mapping(path)["projects"]
    if project not in projects:
        raise ValueError(f"No Jira field mapping exists for project {project}")
    return projects[project]
