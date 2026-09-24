"""Regression tests for skill routing and symbolic skill-root aliases."""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[2]


def test_ordinary_conforma_routing_does_not_reference_process_skill():
    router = (REPO_ROOT / "skills/conforma/SKILL.md").read_text()
    analyzer = (REPO_ROOT / "skills/conforma-analyze/SKILL.md").read_text()

    assert "conforma-analyze" in router
    assert "using-superpowers" not in router
    assert "using-superpowers" not in analyzer
    assert "Always route — never execute directly" in router


def test_agent_contract_expands_aliases_instead_of_using_them_as_directories():
    agents = (REPO_ROOT / "AGENTS.md").read_text()

    assert "expand the alias to its mapped root" in agents
    assert "never treat the alias name (`r0`) as a" in agents
    assert "Skill-root aliases are catalog notation, not filesystem directories" in agents


def test_installed_skill_root_uses_expanded_alias_path_when_available():
    mapped_root = Path("/home/wznoinsk/.codex/skills")
    valid_path = mapped_root / "using-superpowers/SKILL.md"
    literal_alias_path = mapped_root / "r0/using-superpowers/SKILL.md"

    if not valid_path.exists():
        pytest.skip("the local Codex skill root is not installed on this host")

    assert valid_path.is_file()
    assert not literal_alias_path.exists()
