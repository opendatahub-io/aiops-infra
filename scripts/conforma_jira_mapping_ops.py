"""Load and validate the C14 project-specific Jira field mapping."""

from __future__ import annotations

import argparse
import json
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
    "field_paths",
    "jql",
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
        if not isinstance(config["field_paths"], dict) or not isinstance(config["jql"], dict):
            raise ValueError(f"Jira mapping for {project} field_paths and jql must be mappings")
        if any(not isinstance(value, list) for value in config["field_paths"].values()):
            raise ValueError(f"Jira mapping for {project} field_paths values must be lists")
    return mapping


def project_config(project: str, path: str | Path = MAPPING_PATH) -> dict:
    """Return one known project mapping; unknown projects are hard errors."""
    projects = load_project_mapping(path)["projects"]
    if project not in projects:
        raise ValueError(f"No Jira field mapping exists for project {project}")
    return projects[project]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and inspect the C14 Jira project-field mapping")
    sub = parser.add_subparsers(dest="command", required=True)
    validate_parser = sub.add_parser("validate", help="Validate the mapping and print it as JSON")
    validate_parser.add_argument("--path", default=str(MAPPING_PATH))
    project_parser = sub.add_parser("project", help="Print one project mapping as JSON")
    project_parser.add_argument("--project", required=True)
    project_parser.add_argument("--path", default=str(MAPPING_PATH))
    args = parser.parse_args()
    if args.command == "validate":
        result = load_project_mapping(args.path)
    else:
        result = project_config(args.project, args.path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
