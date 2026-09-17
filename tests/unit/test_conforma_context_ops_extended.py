"""Extended tests for conforma_context_ops.py — covers discovery error branches,
_atomic_write failure cleanup, and CLI main() branches missed by the base test file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import conforma_context_ops as ctx


class TestDiscoverRunDirErrors:
    def test_explicit_dir_without_context_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No context.yaml"):
            ctx.discover_run_dir(tmp_path / "nope")

    def test_explicit_dir_valid(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir, {})
        assert ctx.discover_run_dir(run_dir) == run_dir

    def test_no_active_link(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        with pytest.raises(FileNotFoundError, match="No active conforma run"):
            ctx.discover_run_dir()

    def test_active_link_not_a_directory(self, tmp_path, monkeypatch):
        """Link points to a regular file → invalid symlink error."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        link = tmp_path / ctx.ACTIVE_LINK
        link.write_text("not a directory")
        with pytest.raises(FileNotFoundError, match="not a valid symlink"):
            ctx.discover_run_dir()

    def test_active_link_target_missing_context(self, tmp_path, monkeypatch):
        """Link points to a directory without context.yaml."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        target = tmp_path / "run2"
        target.mkdir()
        link = tmp_path / ctx.ACTIVE_LINK
        link.symlink_to(target)
        with pytest.raises(FileNotFoundError, match="no context.yaml found there"):
            ctx.discover_run_dir()

    def test_active_link_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "run3"
        ctx.create(run_dir, {})
        ctx.set_active(run_dir)
        assert ctx.discover_run_dir() == run_dir


class TestAtomicWrite:
    def test_cleanup_on_write_failure(self, tmp_path):
        """A failure during the write → temp file removed, exception re-raised."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        target = run_dir / "context.yaml"

        def _fail_dump(*args, **kwargs):
            raise RuntimeError("simulated yaml failure")

        with patch.object(ctx.yaml, "dump", side_effect=_fail_dump):
            with pytest.raises(RuntimeError, match="simulated yaml failure"):
                ctx._atomic_write(target, {"a": 1})
        assert not target.exists()
        leftovers = [p for p in run_dir.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []


class TestMainDirect:
    """Call ctx.main() in-process (subprocess tests don't count toward coverage)."""

    def _main(self, argv, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["conforma_context_ops.py"] + list(argv))
        return ctx.main()

    def test_create_with_initial_json(self, tmp_path, monkeypatch, capsys):
        run_dir = str(tmp_path / "cli-run")
        rc = self._main(["--run-dir", run_dir, "create", "--initial", json.dumps({"environment": "prod"})], monkeypatch)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Created" in out
        assert json.loads(out.split("Created: ", 1)[1].split("\n", 1)[1])["environment"] == "prod"

    def test_create_without_run_dir_uses_workdir(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        rc = self._main(["create"], monkeypatch)
        assert rc == 0
        out = capsys.readouterr().out
        created_path = Path(out.split("Created: ", 1)[1].split("\n", 1)[0])
        # created under a timestamped run dir directly in the work dir
        assert created_path.parent.parent == tmp_path
        assert created_path.is_file()

    def test_show(self, tmp_path, monkeypatch, capsys):
        run_dir = str(tmp_path / "run")
        ctx.create(Path(run_dir), {"environment": "prod"})
        rc = self._main(["--run-dir", run_dir, "show"], monkeypatch)
        assert rc == 0
        assert "environment: prod" in capsys.readouterr().out

    def test_get_scalar(self, tmp_path, monkeypatch, capsys):
        run_dir = str(tmp_path / "run")
        ctx.create(Path(run_dir), {"environment": "prod"})
        rc = self._main(["--run-dir", run_dir, "get", "environment"], monkeypatch)
        assert rc == 0
        assert capsys.readouterr().out.strip() == "prod"

    def test_get_dict_prints_json(self, tmp_path, monkeypatch, capsys):
        run_dir = str(tmp_path / "run")
        ctx.create(Path(run_dir), {"environment": "prod"})
        ctx.put(Path(run_dir), "steps.fetch.csv_files", ["a.csv", "b.csv"])
        rc = self._main(["--run-dir", run_dir, "get", "steps.fetch.csv_files"], monkeypatch)
        assert rc == 0
        assert json.loads(capsys.readouterr().out) == ["a.csv", "b.csv"]

    def test_get_missing_key_returns_1(self, tmp_path, monkeypatch, capsys):
        run_dir = str(tmp_path / "run")
        ctx.create(Path(run_dir), {})
        rc = self._main(["--run-dir", run_dir, "get", "missing.key"], monkeypatch)
        assert rc == 1
        assert "not found" in capsys.readouterr().err

    def test_put_bool_string(self, tmp_path, monkeypatch, capsys):
        run_dir = str(tmp_path / "run")
        ctx.create(Path(run_dir), {})
        rc = self._main(["--run-dir", run_dir, "put", "steps.prerequisites.slack_available", "true"], monkeypatch)
        assert rc == 0
        assert "Set steps.prerequisites.slack_available" in capsys.readouterr().out
        assert ctx.get(Path(run_dir), "steps.prerequisites.slack_available") is True

    def test_put_json_value(self, tmp_path, monkeypatch):
        run_dir = str(tmp_path / "run")
        ctx.create(Path(run_dir), {})
        rc = self._main(
            ["--run-dir", run_dir, "put", "resolve.policy_files", json.dumps(["a.yaml", "b.yaml"])], monkeypatch
        )
        assert rc == 0
        assert ctx.get(Path(run_dir), "resolve.policy_files") == ["a.yaml", "b.yaml"]

    def test_put_plain_string_stays_string(self, tmp_path, monkeypatch):
        run_dir = str(tmp_path / "run")
        ctx.create(Path(run_dir), {})
        rc = self._main(["--run-dir", run_dir, "put", "user_query", "rhoai-3.5"], monkeypatch)
        assert rc == 0
        assert ctx.get(Path(run_dir), "user_query") == "rhoai-3.5"

    def test_missing_run_dir_raises_file_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        with pytest.raises(FileNotFoundError, match="No active conforma run"):
            self._main(["show"], monkeypatch)
