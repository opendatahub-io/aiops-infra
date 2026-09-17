"""Tests for deterministic Conforma TODO preview presentation."""

from __future__ import annotations

from pathlib import Path

import pytest

import present_conforma_report as mod


def _todo(*sections: str) -> str:
    if sections and sections[0] == "status":
        sections = ("status\n\n" + _table(), *sections[1:])
    return "## TODO\n\n" + "\n\n".join(
        f"### TODO #{number}\n\n{body}" for number, body in enumerate(sections)
    )


def _table() -> str:
    return "| # | Value |\n|---|---|\n| 1 | ok |"


def test_validate_accepts_all_required_tables():
    content = _todo("status", *([_table()] * 6))

    assert mod.validate_todo_content(content) == []


def test_validate_checks_optional_zero_count_sections():
    content = _todo("status", *([_table()] * 6))
    content += "\n\n### TODO #7 — 0 warnings becoming violations\n\nNo warnings were found.\n"

    assert mod.validate_todo_content(content) == ["TODO #7 is missing its Markdown table"]


def test_validate_accepts_complete_optional_zero_count_section():
    content = _todo("status", *([_table()] * 6))
    content += "\n\n### TODO #7 — 0 warnings becoming violations\n\n" + _table() + "\n"

    assert mod.validate_todo_content(content) == []


def test_validate_rejects_missing_table_in_todo_section():
    content = _todo("status", _table(), "prose only", *([_table()] * 4))

    assert mod.validate_todo_content(content) == ["TODO #2 is missing its Markdown table"]


def test_validate_rejects_missing_section():
    content = _todo("status", *([_table()] * 5))

    assert mod.validate_todo_content(content) == ["TODO #6 is missing"]


def test_validate_rejects_existing_markers():
    content = _todo("status", *([_table()] * 6)) + "\nBEGIN_VERBATIM_TODO\n"

    assert "presentation markers" in mod.validate_todo_content(content)[0]


def test_present_todo_preserves_content_inside_markers(tmp_path: Path):
    content = _todo("status", *([_table()] * 6)) + "\n"
    path = tmp_path / "conforma-todo.md"
    path.write_text(content, encoding="utf-8")

    output = mod.present_todo(path)

    assert output == f"{mod.BEGIN_MARKER}\n{content}{mod.END_MARKER}\n"


def test_present_todo_fails_before_output_for_invalid_content(tmp_path: Path):
    path = tmp_path / "conforma-todo.md"
    path.write_text(_todo("status", _table(), "missing table", *([_table()] * 4)), encoding="utf-8")

    with pytest.raises(ValueError, match="TODO #2 is missing its Markdown table"):
        mod.present_todo(path)
