#!/usr/bin/env python3
"""Validate and present the generated Conforma TODO preview verbatim.

The generated file is the source of truth. This script only validates its
required TODO/table structure and wraps the unchanged file content in markers
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

BEGIN_MARKER = "BEGIN_VERBATIM_TODO"
END_MARKER = "END_VERBATIM_TODO"
BEGIN_SUBMISSION_MARKER = "BEGIN_SUBMISSION_QUESTION"
END_SUBMISSION_MARKER = "END_SUBMISSION_QUESTION"
REQUIRED_TODO_NUMBERS = range(1, 7)
CONTEXT_CONFIRMATION_HEADING = "### Conforma Workflow — Context Confirmation"
TODO_HEADING_RE = re.compile(r"^### TODO #(\d+)\b.*$", re.MULTILINE)
TABLE_HEADER_RE = re.compile(r"^\|[^\n]*\|\s*$", re.MULTILINE)
TABLE_SEPARATOR_RE = re.compile(r"^\|\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)+\|\s*$", re.MULTILINE)


def _todo_sections(content: str) -> dict[int, str]:
    """Return TODO section bodies keyed by their numeric heading."""
    matches = list(TODO_HEADING_RE.finditer(content))
    sections: dict[int, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections[int(match.group(1))] = content[match.end() : end]
    return sections


def validate_todo_content(content: str) -> list[str]:
    """Return deterministic validation errors for a complete TODO preview.

    The required sections protect the stable core of the report. Every section
    actually emitted by the generator is also checked so optional sections,
    including zero-count sections, cannot be abbreviated or emitted without
    their full Markdown table.
    """
    errors: list[str] = []
    sections = _todo_sections(content)

    if not content.strip():
        return ["TODO preview is empty"]

    if BEGIN_MARKER in content or END_MARKER in content:
        errors.append("TODO preview contains presentation markers; markers belong only in script output")

    if "## TODO" not in content:
        errors.append("TODO preview is missing the '## TODO' section")

    context_start = content.find(CONTEXT_CONFIRMATION_HEADING)
    todo_start = content.find("## TODO")
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

    for number in REQUIRED_TODO_NUMBERS:
        body = sections.get(number)
        if body is None:
            errors.append(f"TODO #{number} is missing")

    for number, body in sorted(sections.items()):
        if not TABLE_HEADER_RE.search(body):
            errors.append(f"TODO #{number} is missing its Markdown table")
        elif not TABLE_SEPARATOR_RE.search(body):
            errors.append(f"TODO #{number} is missing its Markdown table separator")

    return errors


def resolve_todo_path(run_dir: Path) -> Path:
    """Resolve the TODO file recorded in the active run context."""
    relative_path = conforma_context_ops.get(
        run_dir,
        "steps.resolution_guide.todo_file",
        "conforma-todo.md",
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
    parser = argparse.ArgumentParser(description="Validate and present the generated Conforma TODO preview verbatim")
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
