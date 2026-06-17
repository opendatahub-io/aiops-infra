"""Tests for component_alias_ops.py."""

from __future__ import annotations

import component_alias_ops as mod


class TestLoadAliases:
    def test_loads_groups_from_yaml(self, tmp_path):
        f = tmp_path / "aliases.yaml"
        f.write_text(
            "alias_groups:\n"
            "  - names:\n"
            "      - comp-a\n"
            "      - comp-b\n"
            "    note: test\n"
        )
        aliases = mod.load_aliases(f)
        assert "comp-a" in aliases
        assert "comp-b" in aliases
        assert aliases["comp-a"] == {"comp-a", "comp-b"}
        assert aliases["comp-b"] == {"comp-a", "comp-b"}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        f = tmp_path / "aliases.yaml"
        f.write_text("")
        assert mod.load_aliases(f) == {}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert mod.load_aliases(tmp_path / "nonexistent.yaml") == {}

    def test_single_name_group_ignored(self, tmp_path):
        f = tmp_path / "aliases.yaml"
        f.write_text(
            "alias_groups:\n"
            "  - names:\n"
            "      - only-one\n"
            "    note: too few\n"
        )
        assert mod.load_aliases(f) == {}

    def test_multiple_groups(self, tmp_path):
        f = tmp_path / "aliases.yaml"
        f.write_text(
            "alias_groups:\n"
            "  - names: [a, b]\n"
            "    note: first\n"
            "  - names: [x, y, z]\n"
            "    note: second\n"
        )
        aliases = mod.load_aliases(f)
        assert aliases["a"] == {"a", "b"}
        assert aliases["x"] == {"x", "y", "z"}
        assert aliases["z"] == {"x", "y", "z"}


class TestExpandComponentSet:
    def test_expands_with_aliases(self):
        aliases = {"comp-a": {"comp-a", "comp-b"}, "comp-b": {"comp-a", "comp-b"}}
        result = mod.expand_component_set({"comp-a"}, aliases)
        assert result == {"comp-a", "comp-b"}

    def test_unknown_names_pass_through(self):
        aliases = {"comp-a": {"comp-a", "comp-b"}, "comp-b": {"comp-a", "comp-b"}}
        result = mod.expand_component_set({"unknown-comp"}, aliases)
        assert result == {"unknown-comp"}

    def test_empty_aliases_returns_original(self):
        result = mod.expand_component_set({"comp-a", "comp-b"}, {})
        assert result == {"comp-a", "comp-b"}

    def test_mixed_known_and_unknown(self):
        aliases = {"comp-a": {"comp-a", "comp-b"}, "comp-b": {"comp-a", "comp-b"}}
        result = mod.expand_component_set({"comp-a", "other"}, aliases)
        assert result == {"comp-a", "comp-b", "other"}

    def test_accepts_list_input(self):
        aliases = {"comp-a": {"comp-a", "comp-b"}, "comp-b": {"comp-a", "comp-b"}}
        result = mod.expand_component_set(["comp-a"], aliases)
        assert result == {"comp-a", "comp-b"}


class TestFindAliasMatch:
    def test_returns_none_for_direct_match(self):
        aliases = {"a": {"a", "b"}, "b": {"a", "b"}}
        assert mod.find_alias_match({"a", "b"}, "a", aliases) is None

    def test_returns_alias_when_candidate_not_in_requested(self):
        aliases = {"a": {"a", "b"}, "b": {"a", "b"}}
        result = mod.find_alias_match({"a"}, "b", aliases)
        assert result == "a"

    def test_returns_none_for_unknown_candidate(self):
        aliases = {"a": {"a", "b"}, "b": {"a", "b"}}
        assert mod.find_alias_match({"a"}, "unknown", aliases) is None

    def test_returns_none_with_empty_aliases(self):
        assert mod.find_alias_match({"a"}, "b", {}) is None
