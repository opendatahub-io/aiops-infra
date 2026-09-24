#!/usr/bin/env python3
"""Validate and present the generated Conforma TODO/DONE/WARNINGS preview verbatim.

The generated file is the source of truth. This script only validates its
required TODO/DONE/WARNINGS structure and wraps the unchanged file content in markers
so a caller can relay it without reconstructing or summarizing it. It also
emits the deterministic submission question for the active run, so completion
of the report presentation cannot omit the required submission decision.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import _setup_env  # noqa: F401
import conforma_context_ops
from submit_resolution_guide import build_submission_prompt

BEGIN_MARKER = "BEGIN_VERBATIM_TODO_AND_DONE"
END_MARKER = "END_VERBATIM_TODO_AND_DONE"
BEGIN_SUBMISSION_MARKER = "BEGIN_SUBMISSION_QUESTION"
END_SUBMISSION_MARKER = "END_SUBMISSION_QUESTION"
CONTEXT_CONFIRMATION_HEADING = "### Conforma Workflow — Context Confirmation"
SECTION_MARKER_RE = re.compile(r"^<!-- conforma-section: ([a-z0-9-]+) -->$", re.MULTILINE)
SECTION_HEADING_RE = re.compile(r"^### (TODO|DONE) #(\d+) — (.+?)\s*$", re.MULTILINE)
WARNINGS_HEADING_RE = re.compile(r"^## WARNINGS$", re.MULTILINE)
TABLE_HEADER_RE = re.compile(r"^\|[^\n]*\|\s*$", re.MULTILINE)
TABLE_SEPARATOR_RE = re.compile(r"^\|\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)+\|\s*$", re.MULTILINE)
VIOLATION_ACCOUNTING_RE = re.compile(
    r"^<!-- conforma-violation-accounting: source=(\d+); todo=(\d+); done=(\d+) -->$",
    re.MULTILINE,
)


def _section_groups(content: str) -> dict[str, list[tuple[int, str, str, str]]]:
    """Return marked TODO/DONE headings and bodies in their source order."""
    marker_matches = list(SECTION_MARKER_RE.finditer(content))
    heading_matches = list(SECTION_HEADING_RE.finditer(content))
    headings_by_start = {match.start(): match for match in heading_matches}
    groups: dict[str, list[tuple[int, str, str, str]]] = {"TODO": [], "DONE": []}
    for index, marker in enumerate(marker_matches):
        heading_start = marker.end()
        if content.startswith("\n", heading_start):
            heading_start += 1
        heading = headings_by_start.get(heading_start)
        if heading is None:
            continue
        end = marker_matches[index + 1].start() if index + 1 < len(marker_matches) else len(content)
        status, number, title = heading.group(1), int(heading.group(2)), heading.group(3)
        groups.setdefault(status, []).append(
            (number, title, content[heading.end() : end], marker.group(1))
        )
    return groups


EXPECTED_SECTION_KINDS = (
    "tooling",
    "violations-without-exception-or-merge-request",
    "expiring-exceptions-without-merge-request",
    "expiring-exceptions-merge-request-before-release",
    "expiring-exceptions-merge-request-after-release",
    "merge-request-expiring-before-release",
    "open-merge-requests-not-merged",
    "warnings-before-release",
    "warnings-after-release",
    "covered-violations",
)


def validate_todo_content(content: str) -> list[str]:
    """Return deterministic validation errors for a complete TODO/DONE/WARNINGS preview.

    The marker inventory is the contract: every logical section must occur
    exactly once, including zero-count sections. Bodies cannot be abbreviated;
    non-tooling sections must retain their Markdown table.
    """
    errors: list[str] = []
    if not content.strip():
        return ["TODO preview is empty"]

    accounting = VIOLATION_ACCOUNTING_RE.findall(content)
    if len(accounting) != 1:
        errors.append("TODO/DONE preview must contain exactly one violation accounting marker")
    elif int(accounting[0][0]) != int(accounting[0][1]) + int(accounting[0][2]):
        errors.append("Violation accounting gate failed: source must equal TODO plus DONE owners")

    if BEGIN_MARKER in content or END_MARKER in content:
        errors.append("TODO preview contains presentation markers; markers belong only in script output")

    todo_start = content.find("## TODO")
    done_start = content.find("## DONE")
    warning_headings = list(WARNINGS_HEADING_RE.finditer(content))
    if todo_start == -1:
        errors.append("TODO preview is missing the '## TODO' section")
    if done_start == -1:
        errors.append("TODO preview is missing the '## DONE' section")
    if todo_start != -1 and done_start != -1 and todo_start > done_start:
        errors.append("The TODO section must appear before the DONE section")
    if len(warning_headings) != 1:
        errors.append("TODO preview must contain exactly one '## WARNINGS' section")
    elif done_start == -1 or warning_headings[0].start() < done_start:
        errors.append("The WARNINGS section must appear after the DONE section")

    context_start = content.find(CONTEXT_CONFIRMATION_HEADING)
    if context_start == -1:
        errors.append("TODO preview is missing the context confirmation section")
    elif todo_start == -1 or context_start > todo_start:
        errors.append("Context confirmation section must appear before the TODO section")
    else:
        context_body = content[context_start + len(CONTEXT_CONFIRMATION_HEADING) : todo_start]
        if not TABLE_HEADER_RE.search(context_body):
            errors.append("Context confirmation section is missing its Markdown table")
        elif not TABLE_SEPARATOR_RE.search(context_body):
            errors.append("Context confirmation section is missing its Markdown table separator")

    groups = _section_groups(content)
    marked_ranges = {
        marker.start(): marker.end()
        for marker in SECTION_MARKER_RE.finditer(content)
    }
    for heading in SECTION_HEADING_RE.finditer(content):
        preceding_marker = content.rfind("<!-- conforma-section:", 0, heading.start())
        if preceding_marker not in marked_ranges or content[marked_ranges[preceding_marker] : heading.start()].strip():
            errors.append(f"{heading.group(1)} #{heading.group(2)} is missing its conforma-section marker")

    seen_kinds: set[str] = set()
    for status in ("TODO", "DONE"):
        sections = groups[status]
        numbers = [number for number, _, _, _ in sections]
        if numbers != list(range(len(numbers))):
            errors.append(f"{status} section numbers must be independent and contiguous from #0")
        if len(numbers) != len(set(numbers)):
            errors.append(f"{status} section numbers must not be duplicated")
        for number, title, body, kind in sections:
            if kind not in EXPECTED_SECTION_KINDS:
                errors.append(f"{status} #{number} has an unknown section marker: {kind}")
            elif kind in seen_kinds:
                errors.append(f"Section inventory contains a duplicate: {kind}")
            else:
                seen_kinds.add(kind)
            if kind == "tooling" and number != 0:
                errors.append(f"Tooling must always be {status} #0")
            if not body.strip():
                errors.append(f"{status} #{number} has an empty body")
            elif kind != "tooling":
                if not TABLE_HEADER_RE.search(body):
                    errors.append(f"{status} #{number} is missing its Markdown table")
                elif not TABLE_SEPARATOR_RE.search(body):
                    errors.append(f"{status} #{number} is missing its Markdown table separator")

    missing = set(EXPECTED_SECTION_KINDS) - seen_kinds
    for kind in sorted(missing):
        errors.append(f"TODO/DONE section inventory is missing: {kind}")
    if "tooling" not in seen_kinds:
        errors.append("TODO/DONE section inventory is missing: tooling")

    return errors


def resolve_todo_path(run_dir: Path) -> Path:
    """Resolve the TODO file recorded in the active run context."""
    relative_path = conforma_context_ops.get(
        run_dir,
        "steps.resolution_guide.todo_file",
        "conforma-todo-and-done.md",
    )
    path = Path(str(relative_path)).expanduser()
    return path if path.is_absolute() else run_dir / path


def resolve_guide_path(run_dir: Path) -> Path:
    """Resolve the generated guide path recorded in the active run context."""
    relative_path = conforma_context_ops.get(
        run_dir,
        "steps.resolution_guide.guide_file",
        "conforma-resolution-guide.md",
    )
    path = Path(str(relative_path)).expanduser()
    return path if path.is_absolute() else run_dir / path


def submission_prompt(run_dir: Path) -> str:
    """Return the deterministic submission question for the active run."""
    release = conforma_context_ops.get(run_dir, "application.release")
    environment = conforma_context_ops.get(run_dir, "environment", "prod")
    guide_path = resolve_guide_path(run_dir)
    prompt = build_submission_prompt(
        guide_file=str(guide_path),
        release=str(release),
        environment=str(environment),
    )
    options = "\n".join(f"- {option}" for option in prompt["question_options"])
    return f"{BEGIN_SUBMISSION_MARKER}\n{prompt['question_text']}\n\n{options}\n{END_SUBMISSION_MARKER}\n"


def present_todo(todo_path: Path, run_dir: Path | None = None) -> str:
    """Validate and return marked output containing the TODO file unchanged."""
    content = todo_path.read_text(encoding="utf-8")
    errors = validate_todo_content(content)
    if errors:
        raise ValueError("Generated TODO preview failed validation:\n- " + "\n- ".join(errors))

    output = f"{BEGIN_MARKER}\n{content}"
    if not content.endswith("\n"):
        output += "\n"
    output += f"{END_MARKER}\n"
    if run_dir is not None:
        output += f"\n{submission_prompt(run_dir)}"
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and present the generated Conforma TODO/DONE preview verbatim")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Path to the run directory; auto-discovered from .conforma-active when omitted",
    )
    args = parser.parse_args()

    try:
        run_dir = conforma_context_ops.discover_run_dir(args.run_dir)
        todo_path = resolve_todo_path(run_dir)
        output = present_todo(todo_path, run_dir)
    except (FileNotFoundError, KeyError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
