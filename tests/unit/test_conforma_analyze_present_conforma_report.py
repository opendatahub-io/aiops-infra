"""Tests for deterministic Conforma TODO/DONE preview presentation."""

from __future__ import annotations

from pathlib import Path

import pytest

import present_conforma_report as mod


SECTION_KINDS = (
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


def _table() -> str:
    return "| # | Value |\n|---|---|\n| 1 | ok |"


def _preview(
    *,
    todo_kinds: tuple[str, ...] = SECTION_KINDS[:1],
    done_kinds: tuple[str, ...] = SECTION_KINDS[1:],
    todo_numbers: tuple[int, ...] | None = None,
    done_numbers: tuple[int, ...] | None = None,
    body: str | None = None,
) -> str:
    context = (
        "### Conforma Workflow — Context Confirmation\n\n"
        "| Field | Value |\n|---|---|\n| Release | rhoai-3.6 |\n\n"
    )
    todo_numbers = todo_numbers or tuple(range(len(todo_kinds)))
    done_numbers = done_numbers or tuple(range(len(done_kinds)))
    sections = ["## TODO", ""]
    for number, kind in zip(todo_numbers, todo_kinds):
        sections.extend(
            [
                f"<!-- conforma-section: {kind} -->",
                f"### TODO #{number} — {kind}",
                "",
                body or _table(),
                "",
            ]
        )
    sections.extend(["## DONE", ""])
    for number, kind in zip(done_numbers, done_kinds):
        sections.extend(
            [
                f"<!-- conforma-section: {kind} -->",
                f"### DONE #{number} — {kind}",
                "",
                body or _table(),
                "",
            ]
        )
    sections.extend(
        [
            "## WARNINGS",
            "",
            "| # | Warning |",
            "|---|---|",
            "| | No generic exception-expiry records |",
        ]
    )
    return context + "<!-- conforma-violation-accounting: source=11; todo=1; done=10 -->\n\n" + "\n".join(sections)


def test_validate_accepts_complete_mixed_inventory():
    assert mod.validate_todo_content(_preview()) == []


def test_validate_accepts_all_sections_in_done_group():
    assert mod.validate_todo_content(_preview(todo_kinds=(), done_kinds=SECTION_KINDS)) == []


def test_validate_rejects_missing_section_marker():
    content = _preview().replace("<!-- conforma-section: warnings-after-release -->\n", "", 1)

    assert "missing its conforma-section marker" in "\n".join(mod.validate_todo_content(content))


def test_validate_rejects_missing_inventory_section():
    content = _preview(done_kinds=SECTION_KINDS[1:-1])

    assert "covered-violations" in "\n".join(mod.validate_todo_content(content))


def test_validate_rejects_duplicate_inventory_section():
    content = _preview(done_kinds=("covered-violations",) + SECTION_KINDS[1:])

    assert "duplicate: covered-violations" in "\n".join(mod.validate_todo_content(content))


def test_validate_rejects_non_contiguous_independent_numbering():
    content = _preview(todo_kinds=("tooling", "warnings-before-release"), todo_numbers=(0, 2))

    assert "TODO section numbers must be independent and contiguous from #0" in mod.validate_todo_content(content)


def test_validate_requires_tooling_number_zero_in_done_group():
    content = _preview(todo_kinds=(), done_kinds=SECTION_KINDS, done_numbers=tuple(range(1, 11)))

    assert "Tooling must always be DONE #0" in mod.validate_todo_content(content)


def test_validate_rejects_missing_warnings_section():
    content = _preview().split("## WARNINGS", 1)[0]

    assert "exactly one '## WARNINGS' section" in "\n".join(mod.validate_todo_content(content))


def test_validate_rejects_warnings_before_done():
    content = _preview()
    warnings = content[content.index("## WARNINGS") :]
    content = content[: content.index("## WARNINGS")]
    done_start = content.index("## DONE")
    content = content[:done_start] + warnings + content[done_start:]

    assert "WARNINGS section must appear after the DONE section" in "\n".join(
        mod.validate_todo_content(content)
    )


def test_validate_rejects_empty_done_body():
    heading = "### DONE #0 — violations-without-exception-or-merge-request\n\n"
    before, after = _preview().split(heading, 1)
    content = before + heading + after.split(_table(), 1)[1]

    assert "DONE #0 has an empty body" in mod.validate_todo_content(content)


def test_validate_rejects_missing_table_in_non_tooling_section():
    content = _preview().replace(
        "### DONE #0 — violations-without-exception-or-merge-request\n\n" + _table(),
        "### DONE #0 — violations-without-exception-or-merge-request\n\nNo details.",
    )

    assert "DONE #0 is missing its Markdown table" in mod.validate_todo_content(content)


def test_validate_rejects_existing_presentation_markers():
    content = _preview() + "\nBEGIN_VERBATIM_TODO_AND_DONE\n"

    assert "presentation markers" in mod.validate_todo_content(content)[0]


def test_present_todo_preserves_content_inside_markers(tmp_path: Path):
    content = _preview() + "\n"
    path = tmp_path / "conforma-todo-and-done.md"
    path.write_text(content, encoding="utf-8")

    assert mod.present_todo(path) == f"{mod.BEGIN_MARKER}\n{content}{mod.END_MARKER}\n"


def test_submission_prompt_is_deterministic_from_context(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "context.yaml").write_text(
        "application:\n  release: rhoai-3.6-ea.2\nenvironment: prod\n"
        "steps:\n  resolution_guide:\n    guide_file: conforma-resolution-guide.md\n",
        encoding="utf-8",
    )

    assert mod.submission_prompt(run_dir) == (
        "BEGIN_SUBMISSION_QUESTION\n"
        "Submit prod/conforma-resolution-guide.md to GitHub "
        "(red-hat-data-services/conforma-reporter, branch rhoai-3.6-ea.2)?\n\n"
        "- Yes, submit\n"
        "- No, skip\n"
        "END_SUBMISSION_QUESTION\n"
    )


def test_resolve_todo_path_uses_new_default(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "context.yaml").write_text("steps: {}\n", encoding="utf-8")

    assert mod.resolve_todo_path(run_dir) == run_dir / "conforma-todo-and-done.md"


def test_present_todo_includes_submission_prompt(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "context.yaml").write_text(
        "application:\n  release: rhoai-3.6-ea.2\nenvironment: prod\n"
        "steps:\n  resolution_guide:\n    guide_file: conforma-resolution-guide.md\n",
        encoding="utf-8",
    )
    content = _preview() + "\n"
    path = run_dir / "conforma-todo-and-done.md"
    path.write_text(content, encoding="utf-8")

    output = mod.present_todo(path, run_dir)

    assert output.endswith(mod.submission_prompt(run_dir))
    assert "Submit prod/conforma-resolution-guide.md to GitHub" in output


def test_present_todo_fails_before_output_for_invalid_content(tmp_path: Path):
    path = tmp_path / "conforma-todo-and-done.md"
    content = _preview().replace(
        "### DONE #0 — violations-without-exception-or-merge-request\n\n" + _table(),
        "### DONE #0 — violations-without-exception-or-merge-request\n\nmissing table",
    )
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="DONE #0 is missing its Markdown table"):
        mod.present_todo(path)


def test_validate_rejects_missing_context_confirmation():
    content = _preview().split("## TODO", 1)[1]

    errors = mod.validate_todo_content("## TODO" + content)
    assert "TODO preview is missing the context confirmation section" in errors


def test_validate_rejects_context_confirmation_without_table():
    content = _preview().replace(
        "| Field | Value |\n|---|---|\n| Release | rhoai-3.6 |", "Context is present."
    )

    assert mod.validate_todo_content(content) == [
        "Context confirmation section is missing its Markdown table"
    ]
