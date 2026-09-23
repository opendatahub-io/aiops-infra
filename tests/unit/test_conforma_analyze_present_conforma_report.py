"""Tests for deterministic Conforma TODO preview presentation."""

from __future__ import annotations

from pathlib import Path

import pytest

import present_conforma_report as mod


def _todo(*sections: str) -> str:
    if sections and sections[0] == "status":
        sections = ("status\n\n" + _table(), *sections[1:])
    context = (
        "### Conforma Workflow — Context Confirmation\n\n"
        "| Field | Value |\n|---|---|\n| Release | rhoai-3.6 |\n\n"
    )
    return context + "## TODO\n\n" + "\n\n".join(
        f"### TODO #{number}\n\n{body}" for number, body in enumerate(sections)
    )


def _table() -> str:
    return "| # | Value |\n|---|---|\n| 1 | ok |"


def test_validate_accepts_all_required_tables():
    content = _todo("status", *([_table()] * 7))

    assert mod.validate_todo_content(content) == []


def test_validate_rejects_prose_only_todo_zero():
    content = _todo("status", *([_table()] * 7))
    content = content.replace("### TODO #0\n\nstatus\n\n" + _table(), "### TODO #0 — Tooling status: healthy\n\nTooling is healthy.")
    content += "\n".join(f"### TODO #{number}\n\n{_table()}" for number in range(1, 7))

    assert mod.validate_todo_content(content) == ["TODO #0 is missing its Markdown table"]


def test_validate_checks_optional_zero_count_sections():
    content = _todo("status", *([_table()] * 7))
    content += "\n\n### TODO #8 — 0 warnings becoming violations\n\nNo warnings were found.\n"

    assert mod.validate_todo_content(content) == ["TODO #8 is missing its Markdown table"]


def test_validate_accepts_complete_optional_zero_count_section():
    content = _todo("status", *([_table()] * 7))
    content += "\n\n### TODO #8 — 0 warnings becoming violations\n\n" + _table() + "\n"

    assert mod.validate_todo_content(content) == []


def test_validate_rejects_missing_table_in_todo_section():
    content = _todo("status", _table(), "prose only", *([_table()] * 5))

    assert mod.validate_todo_content(content) == ["TODO #2 is missing its Markdown table"]


def test_validate_rejects_missing_section():
    content = _todo("status", *([_table()] * 6))

    assert mod.validate_todo_content(content) == ["TODO #7 is missing"]


def test_validate_rejects_existing_markers():
    content = _todo("status", *([_table()] * 7)) + "\nBEGIN_VERBATIM_TODO\n"

    assert "presentation markers" in mod.validate_todo_content(content)[0]


def test_present_todo_preserves_content_inside_markers(tmp_path: Path):
    content = _todo("status", *([_table()] * 7)) + "\n"
    path = tmp_path / "conforma-todo.md"
    path.write_text(content, encoding="utf-8")

    output = mod.present_todo(path)

    assert output == f"{mod.BEGIN_MARKER}\n{content}{mod.END_MARKER}\n"


def test_submission_prompt_is_deterministic_from_context(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "context.yaml").write_text(
        "application:\n  release: rhoai-3.6-ea.2\nenvironment: prod\n"
        "steps:\n  resolution_guide:\n    guide_file: conforma-resolution-guide.md\n",
        encoding="utf-8",
    )

    prompt = mod.submission_prompt(run_dir)

    assert prompt == (
        "BEGIN_SUBMISSION_QUESTION\n"
        "Submit prod/conforma-resolution-guide.md to GitHub "
        "(red-hat-data-services/conforma-reporter, branch rhoai-3.6-ea.2)?\n\n"
        "- Yes, submit\n"
        "- No, skip\n"
        "END_SUBMISSION_QUESTION\n"
    )


def test_present_todo_includes_submission_prompt(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "context.yaml").write_text(
        "application:\n  release: rhoai-3.6-ea.2\nenvironment: prod\n"
        "steps:\n  resolution_guide:\n    guide_file: conforma-resolution-guide.md\n",
        encoding="utf-8",
    )
    content = _todo("status", *([_table()] * 7)) + "\n"
    path = run_dir / "conforma-todo.md"
    path.write_text(content, encoding="utf-8")

    output = mod.present_todo(path, run_dir)

    assert output.endswith(mod.submission_prompt(run_dir))
    assert "Submit prod/conforma-resolution-guide.md to GitHub" in output


def test_present_todo_fails_before_output_for_invalid_content(tmp_path: Path):
    path = tmp_path / "conforma-todo.md"
    path.write_text(_todo("status", _table(), "missing table", *([_table()] * 4)), encoding="utf-8")

    with pytest.raises(ValueError, match="TODO #2 is missing its Markdown table"):
        mod.present_todo(path)


def test_validate_rejects_missing_context_confirmation():
    content = "## TODO\n\n" + "\n\n".join(
        f"### TODO #{number}\n\n{_table()}" for number in range(8)
    )

    assert mod.validate_todo_content(content) == [
        "TODO preview is missing the context confirmation section"
    ]


def test_validate_rejects_context_confirmation_without_table():
    content = "### Conforma Workflow — Context Confirmation\n\nContext is present.\n\n" + _todo(
        "status", *([_table()] * 7)
    ).split("## TODO", 1)[1]

    assert mod.validate_todo_content(content) == [
        "Context confirmation section is missing its Markdown table"
    ]
