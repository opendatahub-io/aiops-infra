#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Resolve the RHEL major of the effective base image of a Dockerfile's final stage."""

import argparse
import os
import re
import shlex
import sys
import urllib.parse
import urllib.request
from typing import Optional

from rhel_version_contract import resolve_base_rhel_version


def fetch(source: str) -> str:
    try:
        if source.startswith(("http://", "https://")):
            request = urllib.request.Request(source)
            token = os.environ.get("GITHUB_TOKEN")
            if token and urllib.parse.urlparse(source).hostname == "raw.githubusercontent.com":
                request.add_unredirected_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(request) as response:
                return response.read().decode("utf-8")
        with open(source, encoding="utf-8") as dockerfile:
            return dockerfile.read()
    except Exception as exc:
        raise ValueError(f"could not fetch/read Dockerfile {source!r}: {exc}") from exc


def dockerfile_url(repo_url: str, repo_branch: str, context_path: str, dockerfile_path: str) -> str:
    parsed = urllib.parse.urlparse(repo_url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("repo_url must be an HTTPS GitHub repository URL")
    repo_parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(repo_parts) != 2:
        raise ValueError("repo_url must identify a GitHub owner and repository")
    repo_parts[-1] = repo_parts[-1].removesuffix(".git")
    path_parts = repo_parts + [part for part in repo_branch.split("/") if part]
    for label, value in (("context_path", context_path), ("dockerfile_path", dockerfile_path)):
        parts = [part for part in value.strip("/").split("/") if part not in ("", ".")]
        if ".." in parts:
            raise ValueError(f"{label} must not escape the repository root")
        path_parts.extend(parts)
    encoded_path = "/".join(urllib.parse.quote(part, safe="@") for part in path_parts)
    return f"https://raw.githubusercontent.com/{encoded_path}"


def logical_lines(content: str) -> list[tuple[int, str]]:
    """Join Dockerfile continuation lines while preserving their starting line."""
    output: list[tuple[int, str]] = []
    pending = ""
    start = 0
    for number, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not pending:
            start = number
        pending += (" " if pending else "") + stripped.rstrip("\\").strip()
        if stripped.endswith("\\"):
            continue
        if pending:
            output.append((start, pending))
        pending = ""
    if pending:
        raise ValueError(f"Dockerfile line {start}: unfinished continuation")
    return output


def from_stages(content: str) -> list[tuple[int, str, Optional[str]]]:
    stages = []
    for number, line in logical_lines(content):
        if not re.match(r"FROM\b", line, re.IGNORECASE):
            continue
        tokens = line.split()[1:]
        tokens = [token for token in tokens if not token.startswith("--")]
        if not tokens:
            raise ValueError(f"Dockerfile line {number}: FROM has no image")
        image = tokens[0]
        if "$" in image:
            raise ValueError(f"Dockerfile line {number}: cannot resolve ARG-based FROM image {image!r}")
        alias = None
        if len(tokens) >= 3 and tokens[1].lower() == "as":
            alias = tokens[2].lower()
        stages.append((number, image, alias))
    if not stages:
        raise ValueError("Dockerfile has no FROM stages")
    return stages


def image_rhel_version(image: str, line: int) -> str:
    without_digest = image.split("@", 1)[0]
    parts = without_digest.split("/")
    candidates = set()
    for part in parts:
        match = re.match(r"(?:ubi|rhel)-?([1-9][0-9]*)(?:$|[-_.])", part, re.IGNORECASE)
        if match:
            candidates.add(match.group(1))
    # Some UBI references encode the major in the tag (ubi-minimal:9.4).
    basename = parts[-1].split(":", 1)[0].lower()
    tag = parts[-1].split(":", 1)[1] if ":" in parts[-1] else ""
    if basename in {"ubi", "ubi-minimal", "ubi-micro", "ubi-init", "ubi-standard"}:
        tag_match = re.match(r"([1-9][0-9]*)(?:$|[._-])", tag)
        if tag_match:
            candidates.add(tag_match.group(1))
    if len(candidates) != 1:
        raise ValueError(f"Dockerfile line {line}: cannot unambiguously determine RHEL major from {image!r}")
    return f"rhel{next(iter(candidates))}"


def resolve(content: str) -> tuple[str, str]:
    stages = from_stages(content)
    aliases = {alias: (line, image) for line, image, alias in stages if alias}
    line, image, _ = stages[-1]
    visited: set[str] = set()
    while image.lower() in aliases:
        alias = image.lower()
        if alias in visited:
            raise ValueError(f"Dockerfile line {line}: cyclic stage alias {image!r}")
        visited.add(alias)
        line, image = aliases[alias]
    return image_rhel_version(image, line), image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--dockerfile-url")
    source.add_argument("--dockerfile-path")
    parser.add_argument("--repo-url")
    parser.add_argument("--repo-branch")
    parser.add_argument("--context-path", default="./")
    parser.add_argument("--repo-dockerfile-path")
    args = parser.parse_args()
    try:
        repo_args = (args.repo_url, args.repo_branch, args.repo_dockerfile_path)
        if any(repo_args):
            if args.dockerfile_url or args.dockerfile_path or not all(repo_args):
                raise ValueError("provide either direct Dockerfile input or all repo details")
            source_path = dockerfile_url(
                args.repo_url, args.repo_branch, args.context_path, args.repo_dockerfile_path
            )
        else:
            source_path = args.dockerfile_url or args.dockerfile_path
            if not source_path:
                raise ValueError("provide --dockerfile-url, --dockerfile-path, or repo details")
        detected_version, image = resolve(fetch(source_path))
        version = resolve_base_rhel_version(detected_version)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Resolved final-stage base image {image} -> {version}.", file=sys.stderr)
    print(f"BASE_RHEL_VERSION={shlex.quote(version)}")


if __name__ == "__main__":
    main()
