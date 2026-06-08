"""Tests for scripts/yaml_ops.py."""

from __future__ import annotations

import pytest

import yaml_ops


class TestLoad:
    def test_valid_yaml(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("name: test\nvalue: 42\n", encoding="utf-8")

        result = yaml_ops.load(yaml_file)

        assert result == {"name": "test", "value": 42}

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            yaml_ops.load(tmp_path / "missing.yaml")


class TestLoadMultiDoc:
    def test_multiple_docs(self, tmp_path):
        yaml_file = tmp_path / "multi.yaml"
        yaml_file.write_text(
            "---\nname: first\n---\nname: second\nvalue: 2\n",
            encoding="utf-8",
        )

        result = yaml_ops.load_multi_doc(yaml_file)

        assert result == [{"name": "first"}, {"name": "second", "value": 2}]


class TestDump:
    def test_writes_correctly(self, tmp_path):
        out_file = tmp_path / "out.yaml"
        data = {"alpha": 1, "nested": {"beta": True}}

        result = yaml_ops.dump(data, out_file)

        assert result == {"path": str(out_file), "written": True}
        loaded = yaml_ops.load(out_file)
        assert loaded == data


class TestDumpPreservingComments:
    def test_merges_overlay_into_existing_file(self, tmp_path):
        yaml_file = tmp_path / "existing.yaml"
        yaml_file.write_text(
            "name: original\nsettings:\n  enabled: true\n",
            encoding="utf-8",
        )

        result = yaml_ops.dump_preserving_comments({"name": "updated", "extra": "new"}, yaml_file)

        assert result == {"path": str(yaml_file), "written": True}
        loaded = yaml_ops.load(yaml_file)
        assert loaded == {
            "name": "updated",
            "extra": "new",
            "settings": {"enabled": True},
        }


class TestMerge:
    def test_basic(self):
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}

        result = yaml_ops.merge(base, overlay)

        assert result == {"a": 1, "b": 3, "c": 4}
        assert base == {"a": 1, "b": 2}

    def test_nested(self):
        base = {"config": {"retries": 1, "timeout": 30}}
        overlay = {"config": {"timeout": 60, "backoff": 2}}

        result = yaml_ops.merge(base, overlay)

        assert result == {"config": {"retries": 1, "timeout": 60, "backoff": 2}}

    def test_list_handling(self):
        base = {"items": [1, 2], "meta": {"tags": ["a"]}}
        overlay = {"items": [9], "meta": {"tags": ["b", "c"]}}

        result = yaml_ops.merge(base, overlay)

        assert result == {"items": [9], "meta": {"tags": ["b", "c"]}}
