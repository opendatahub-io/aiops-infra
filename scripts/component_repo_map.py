#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["PyYAML>=6.0"]
# ///
"""Update, remove, or verify component_repo_map.json entries from ticket details."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

VERSION_SUFFIX = re.compile(r"-v?\d+-\d+(?:-ea-\d+)?$")


def canonical_component_name(name: str) -> str:
    """Remove a trailing numeric release identity from a Konflux component name."""
    return VERSION_SUFFIX.sub("", name)


def repository_name(inputs: dict) -> str:
    repo_url = inputs.get("repo_url", "")
    name = urlparse(repo_url).path.rstrip("/").split("/")[-1].removesuffix(".git")
    if not name:
        raise ValueError("inputs.repo_url must identify a source repository")
    return name


def expected_entries(details: dict) -> tuple[str, dict[str, str]]:
    inputs = details.get("inputs", details)
    repo_name = repository_name(inputs)

    component_name = inputs.get("component_name", "")
    if not component_name:
        raise ValueError("inputs.component_name is required")
    component_name = canonical_component_name(component_name)
    image_namespace = "rhoai-beta" if inputs.get("release_category") == "Beta" else "rhoai"
    entries = {component_name: f"{image_namespace}/{component_name}-rhel9"}

    for entry in inputs.get("component_repo_map", []):
        name = canonical_component_name(entry.get("component_name", ""))
        image_repository = entry.get("image_repository", "")
        if not name or not image_repository:
            raise ValueError("each inputs.component_repo_map entry needs component_name and image_repository")
        previous = entries.get(name)
        if previous is not None and previous != image_repository:
            raise ValueError(f"conflicting requested image repositories for {name}: {previous} and {image_repository}")
        entries[name] = image_repository

    return repo_name, entries


def removal_targets(details: dict) -> tuple[str, set[str]]:
    inputs = details.get("inputs", details)
    repo_name = repository_name(inputs)
    component_names = [inputs.get("component_name", "")]
    component_names.extend(inputs.get("component_repo_map_components", []))
    if not component_names[0]:
        raise ValueError("inputs.component_name is required")
    if any(not isinstance(name, str) or not name for name in component_names):
        raise ValueError("inputs.component_repo_map_components entries must be non-empty strings")
    return repo_name, {canonical_component_name(name) for name in component_names}


def _validate_map(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("component_repo_map.json must contain a JSON object")
    for repository, components in data.items():
        if not isinstance(repository, str) or not repository or not isinstance(components, dict):
            raise ValueError(f"invalid repository mapping for {repository!r}: expected an object")
        for component, image in components.items():
            if not isinstance(component, str) or not isinstance(image, str) or not image:
                raise ValueError(f"invalid component/image entry under repository {repository!r}")
    return data


def update_map(data: dict, repo_name: str, entries: dict[str, str]) -> bool:
    """Add entries without overwriting conflicts; return whether the map changed."""
    _validate_map(data)
    components = data.setdefault(repo_name, {})
    if not isinstance(components, dict):
        raise ValueError(f"mapping for source repository {repo_name!r} must be an object")

    changed = False
    for component, image in entries.items():
        aliases = [name for name in components if canonical_component_name(name) == component]
        existing_images = {components[name] for name in aliases}
        if existing_images and existing_images != {image}:
            raise ValueError(
                f"conflicting mapping for {repo_name}/{component}: "
                f"existing {sorted(existing_images)}, requested {image!r}"
            )
        if component in components and components[component] != image:
            raise ValueError(
                f"conflicting mapping for {repo_name}/{component}: "
                f"existing {components[component]!r}, requested {image!r}"
            )
        for alias in aliases:
            if alias != component:
                del components[alias]
                changed = True
        if components.get(component) != image:
            components[component] = image
            changed = True

    if changed and not components:
        del data[repo_name]
    return changed


def verify_map(data: dict, repo_name: str, entries: dict[str, str]) -> None:
    _validate_map(data)
    components = data.get(repo_name, {})
    for component, image in entries.items():
        if components.get(component) != image:
            raise ValueError(
                f"mapping is not verified on main: {repo_name}/{component} "
                f"expected {image!r}, found {components.get(component)!r}"
            )
        aliases = [name for name in components if name != component and canonical_component_name(name) == component]
        if aliases:
            raise ValueError(f"versioned aliases remain for {repo_name}/{component}: {aliases}")


def remove_components(data: dict, repo_name: str, component_names: set[str]) -> bool:
    """Remove requested components and prune the source repository when empty."""
    _validate_map(data)
    components = data.get(repo_name)
    if components is None:
        return False

    names_to_remove = {
        name for name in components
        if canonical_component_name(name) in component_names
    }
    for name in names_to_remove:
        del components[name]

    changed = bool(names_to_remove)
    if not components:
        del data[repo_name]
        changed = True
    return changed


def verify_removed(data: dict, repo_name: str, component_names: set[str]) -> None:
    _validate_map(data)
    components = data.get(repo_name)
    if components is None:
        return
    present = sorted(
        name for name in components
        if canonical_component_name(name) in component_names
    )
    if present:
        raise ValueError(f"mapping removal is not verified on main: {repo_name} still contains {present}")
    if not components:
        raise ValueError(f"mapping removal is not verified on main: empty repository key {repo_name!r} remains")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--details", required=True, help="component_onboarding_details.yaml")
    parser.add_argument("--map-file", required=True, help="config/component_repo_map.json")
    parser.add_argument("--verify", action="store_true", help="verify entries instead of updating the map")
    parser.add_argument("--remove", action="store_true", help="remove requested component mapping(s)")
    args = parser.parse_args()

    try:
        details = yaml.safe_load(Path(args.details).read_text(encoding="utf-8"))
        map_path = Path(args.map_file)
        data = _validate_map(json.loads(map_path.read_text(encoding="utf-8")))
        if args.remove:
            repo_name, components = removal_targets(details)
            if args.verify:
                verify_removed(data, repo_name, components)
                print("verified-removed")
                return 0
            changed = remove_components(data, repo_name, components)
        else:
            repo_name, entries = expected_entries(details)
            if args.verify:
                verify_map(data, repo_name, entries)
                print("verified")
                return 0
            changed = update_map(data, repo_name, entries)

        if changed:
            map_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print("removed" if args.remove else "updated")
        else:
            print("already-absent" if args.remove else "already-correct")
        return 0
    except (OSError, json.JSONDecodeError, yaml.YAMLError, AttributeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
