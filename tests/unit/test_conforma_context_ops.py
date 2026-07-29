"""Tests for conforma_context_ops.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import conforma_context_ops as ctx


# ---------------------------------------------------------------------------
# contract_home / expand_home
# ---------------------------------------------------------------------------


class TestContractHome:
    def test_contracts_home_prefix(self):
        home = Path.home()
        assert ctx.contract_home(home / ".conforma" / "run1") == "~/.conforma/run1"

    def test_non_home_path_unchanged(self):
        p = Path("/tmp/something")
        assert ctx.contract_home(p) == "/tmp/something"

    def test_roundtrip(self):
        original = Path.home() / ".conforma" / "20260703-120000"
        contracted = ctx.contract_home(original)
        expanded = ctx.expand_home(contracted)
        assert expanded == original


class TestExpandHome:
    def test_expands_tilde(self):
        result = ctx.expand_home("~/.conforma/run1")
        assert result == Path.home() / ".conforma" / "run1"

    def test_no_tilde_unchanged(self):
        result = ctx.expand_home("/tmp/run1")
        assert result == Path("/tmp/run1")


# ---------------------------------------------------------------------------
# discover_work_dir
# ---------------------------------------------------------------------------


class TestDiscoverWorkDir:
    def test_default_is_home_conforma(self, monkeypatch):
        monkeypatch.delenv("CONFORMA_WORKDIR", raising=False)
        with patch.object(ctx, "DEFAULT_WORK_DIR", Path("/tmp/test-conforma-default")):
            result = ctx.discover_work_dir()
            assert result == Path("/tmp/test-conforma-default")

    def test_env_override(self, tmp_path, monkeypatch):
        work = tmp_path / "custom-workdir"
        monkeypatch.setenv("CONFORMA_WORKDIR", str(work))
        result = ctx.discover_work_dir()
        assert result == work
        assert work.is_dir()

    def test_creates_directory(self, tmp_path, monkeypatch):
        work = tmp_path / "new-dir"
        monkeypatch.setenv("CONFORMA_WORKDIR", str(work))
        assert not work.exists()
        ctx.discover_work_dir()
        assert work.is_dir()


# ---------------------------------------------------------------------------
# discover_run_dir
# ---------------------------------------------------------------------------


class TestDiscoverRunDir:
    def test_explicit_path(self, tmp_path):
        run_dir = tmp_path / "20260703-120000"
        run_dir.mkdir()
        (run_dir / ctx.CONTEXT_FILENAME).write_text("run:\n  run_dir: test\n")
        result = ctx.discover_run_dir(explicit=run_dir)
        assert result == run_dir

    def test_explicit_path_missing_context_raises(self, tmp_path):
        run_dir = tmp_path / "20260703-120000"
        run_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="No context.yaml"):
            ctx.discover_run_dir(explicit=run_dir)

    def test_symlink_follow(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260703-120000"
        run_dir.mkdir()
        (run_dir / ctx.CONTEXT_FILENAME).write_text("run:\n  run_dir: test\n")
        link = tmp_path / ctx.ACTIVE_LINK
        link.symlink_to(run_dir)
        result = ctx.discover_run_dir()
        assert result == run_dir.resolve()

    def test_missing_symlink_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        with pytest.raises(FileNotFoundError, match="No active conforma run"):
            ctx.discover_run_dir()

    def test_broken_symlink_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        link = tmp_path / ctx.ACTIVE_LINK
        link.symlink_to(tmp_path / "nonexistent")
        with pytest.raises(FileNotFoundError):
            ctx.discover_run_dir()

    def test_symlink_exists_but_no_context_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260703-120000"
        run_dir.mkdir()
        link = tmp_path / ctx.ACTIVE_LINK
        link.symlink_to(run_dir)
        with pytest.raises(FileNotFoundError, match="no context.yaml found"):
            ctx.discover_run_dir()


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_creates_context_yaml(self, tmp_path):
        run_dir = tmp_path / "20260703-120000"
        result = ctx.create(run_dir, {"environment": "prod"})
        assert (run_dir / ctx.CONTEXT_FILENAME).is_file()
        assert result["environment"] == "prod"
        assert "run" in result
        assert "created_at" in result["run"]

    def test_auto_populates_run_dir(self, tmp_path):
        run_dir = tmp_path / "my-run"
        result = ctx.create(run_dir)
        assert result["run"]["run_dir"] is not None
        assert "my-run" in result["run"]["run_dir"]

    def test_contracts_home_in_run_dir(self, tmp_path):
        home = Path.home()
        run_dir = home / ".conforma" / "test-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = ctx.create(run_dir)
            assert result["run"]["run_dir"].startswith("~/")
        finally:
            (run_dir / ctx.CONTEXT_FILENAME).unlink(missing_ok=True)
            run_dir.rmdir()

    def test_initializes_empty_steps(self, tmp_path):
        run_dir = tmp_path / "run1"
        result = ctx.create(run_dir)
        assert result["steps"] == {}

    def test_preserves_initial_values(self, tmp_path):
        run_dir = tmp_path / "run1"
        initial = {
            "application": {"name": "rhoai", "release": "rhoai-3.5"},
            "environment": "stage",
        }
        result = ctx.create(run_dir, initial)
        assert result["application"]["name"] == "rhoai"
        assert result["environment"] == "stage"

    def test_does_not_overwrite_existing_created_at(self, tmp_path):
        run_dir = tmp_path / "run1"
        initial = {"run": {"created_at": "2026-01-01T00:00:00+00:00"}}
        result = ctx.create(run_dir, initial)
        assert result["run"]["created_at"] == "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_loads_yaml(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir, {"environment": "prod", "application": {"release": "rhoai-3.5"}})
        data = ctx.load(run_dir)
        assert data["environment"] == "prod"
        assert data["application"]["release"] == "rhoai-3.5"

    def test_expands_tilde_in_run_dir(self, tmp_path):
        run_dir = tmp_path / "run1"
        run_dir.mkdir(parents=True)
        (run_dir / ctx.CONTEXT_FILENAME).write_text(
            "run:\n  run_dir: '~/.conforma/run1'\n"
        )
        data = ctx.load(run_dir)
        assert data["run"]["run_dir"] == str(Path.home() / ".conforma" / "run1")

    def test_expands_tilde_in_clone_dir(self, tmp_path):
        run_dir = tmp_path / "run1"
        run_dir.mkdir(parents=True)
        content = {
            "run": {"run_dir": "~/.conforma/run1", "created_at": "2026-01-01"},
            "steps": {
                "coverage": {
                    "status": "completed",
                    "clone_dir": "~/.conforma/konflux-release-data",
                }
            },
        }
        (run_dir / ctx.CONTEXT_FILENAME).write_text(
            yaml.dump(content, default_flow_style=False)
        )
        data = ctx.load(run_dir)
        expected = str(Path.home() / ".conforma" / "konflux-release-data")
        assert data["steps"]["coverage"]["clone_dir"] == expected

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Context file not found"):
            ctx.load(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# get / put
# ---------------------------------------------------------------------------


class TestGet:
    def test_reads_dotted_key(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir, {"application": {"release": "rhoai-3.5"}})
        assert ctx.get(run_dir, "application.release") == "rhoai-3.5"

    def test_missing_key_raises(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir)
        with pytest.raises(KeyError, match="application"):
            ctx.get(run_dir, "application.release")

    def test_default_value(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir)
        assert ctx.get(run_dir, "application.release", "fallback") == "fallback"

    def test_top_level_key(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir, {"environment": "prod"})
        assert ctx.get(run_dir, "environment") == "prod"


class TestPut:
    def test_sets_dotted_key(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir)
        ctx.put(run_dir, "application.release", "rhoai-3.5")
        assert ctx.get(run_dir, "application.release") == "rhoai-3.5"

    def test_creates_nested_structure(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir)
        ctx.put(run_dir, "steps.fetch.status", "completed")
        assert ctx.get(run_dir, "steps.fetch.status") == "completed"

    def test_overwrites_existing_value(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir, {"environment": "prod"})
        ctx.put(run_dir, "environment", "stage")
        assert ctx.get(run_dir, "environment") == "stage"

    def test_atomic_write_persists(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir)
        ctx.put(run_dir, "application.name", "rhoai")
        raw = yaml.safe_load((run_dir / ctx.CONTEXT_FILENAME).read_text())
        assert raw["application"]["name"] == "rhoai"


# ---------------------------------------------------------------------------
# update_step
# ---------------------------------------------------------------------------


class TestUpdateStep:
    def test_creates_step(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir)
        result = ctx.update_step(run_dir, "fetch", "completed", csv_files=["a.csv"])
        assert result["steps"]["fetch"]["status"] == "completed"
        assert result["steps"]["fetch"]["csv_files"] == ["a.csv"]
        assert "completed_at" in result["steps"]["fetch"]

    def test_pending_status_no_timestamp(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir)
        result = ctx.update_step(run_dir, "parse", "pending")
        assert "completed_at" not in result["steps"]["parse"]

    def test_preserves_other_steps(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir)
        ctx.update_step(run_dir, "fetch", "completed")
        ctx.update_step(run_dir, "parse", "completed")
        data = ctx.load(run_dir)
        assert data["steps"]["fetch"]["status"] == "completed"
        assert data["steps"]["parse"]["status"] == "completed"


# ---------------------------------------------------------------------------
# require
# ---------------------------------------------------------------------------


class TestRequire:
    def test_returns_data_when_all_present(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir, {"application": {"release": "rhoai-3.5"}, "environment": "prod"})
        data = ctx.require(run_dir, "application.release", "environment")
        assert data["application"]["release"] == "rhoai-3.5"

    def test_raises_listing_all_missing(self, tmp_path):
        run_dir = tmp_path / "run1"
        ctx.create(run_dir)
        with pytest.raises(KeyError, match="application.release.*environment"):
            ctx.require(run_dir, "application.release", "environment")


# ---------------------------------------------------------------------------
# resolve_arg
# ---------------------------------------------------------------------------


class TestResolveArg:
    def test_cli_value_wins(self):
        class Args:
            release = "from-cli"
        context = {"application": {"release": "from-context"}}
        assert ctx.resolve_arg(Args(), "release", context, "application.release") == "from-cli"

    def test_context_fallback(self):
        class Args:
            release = None
        context = {"application": {"release": "from-context"}}
        assert ctx.resolve_arg(Args(), "release", context, "application.release") == "from-context"

    def test_both_missing_exits(self):
        class Args:
            release = None
        with pytest.raises(SystemExit):
            ctx.resolve_arg(Args(), "release", {}, "application.release")

    def test_none_context_with_cli(self):
        class Args:
            release = "from-cli"
        assert ctx.resolve_arg(Args(), "release", None, "application.release") == "from-cli"

    def test_none_context_missing_cli_exits(self):
        class Args:
            release = None
        with pytest.raises(SystemExit):
            ctx.resolve_arg(Args(), "release", None, "application.release")


# ---------------------------------------------------------------------------
# set_active
# ---------------------------------------------------------------------------


class TestSetActive:
    def test_creates_symlink(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260703-120000"
        run_dir.mkdir()
        ctx.set_active(run_dir)
        link = tmp_path / ctx.ACTIVE_LINK
        assert link.is_symlink()
        assert link.resolve() == run_dir.resolve()

    def test_replaces_existing_symlink(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        old = tmp_path / "old-run"
        old.mkdir()
        new = tmp_path / "new-run"
        new.mkdir()
        ctx.set_active(old)
        ctx.set_active(new)
        link = tmp_path / ctx.ACTIVE_LINK
        assert link.resolve() == new.resolve()


# ---------------------------------------------------------------------------
# install_wrapper
# ---------------------------------------------------------------------------


class TestInstallWrapper:
    def test_first_install(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        repo = tmp_path / "repo"
        tpl = repo / "scripts" / "conforma_run.sh.tpl"
        tpl.parent.mkdir(parents=True)
        tpl.write_text("#!/bin/bash\necho wrapper\n")

        result = ctx.install_wrapper(repo)
        assert result is True
        target = tmp_path / "bin" / "conforma_run.sh"
        assert target.is_file()
        assert target.read_text() == tpl.read_text()
        assert os.access(target, os.X_OK)

    def test_no_op_when_current(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        repo = tmp_path / "repo"
        tpl = repo / "scripts" / "conforma_run.sh.tpl"
        tpl.parent.mkdir(parents=True)
        tpl.write_text("#!/bin/bash\necho wrapper\n")

        ctx.install_wrapper(repo)
        result = ctx.install_wrapper(repo)
        assert result is False

    def test_updates_when_stale(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        repo = tmp_path / "repo"
        tpl = repo / "scripts" / "conforma_run.sh.tpl"
        tpl.parent.mkdir(parents=True)
        tpl.write_text("#!/bin/bash\necho v1\n")

        ctx.install_wrapper(repo)

        tpl.write_text("#!/bin/bash\necho v2\n")
        result = ctx.install_wrapper(repo)
        assert result is True
        target = tmp_path / "bin" / "conforma_run.sh"
        assert "v2" in target.read_text()

    def test_missing_template_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        result = ctx.install_wrapper(repo)
        assert result is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def _run_cli(self, *args):
        result = subprocess.run(
            [sys.executable, "-m", "conforma_context_ops", *args],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent.parent / "scripts",
        )
        return result

    def test_create_and_show(self, tmp_path):
        run_dir = str(tmp_path / "cli-run")
        result = self._run_cli("--run-dir", run_dir, "create", "--initial", '{"environment":"prod"}')
        assert result.returncode == 0
        assert "Created" in result.stdout

        result = self._run_cli("--run-dir", run_dir, "show")
        assert result.returncode == 0
        assert "environment: prod" in result.stdout

    def test_get_and_put(self, tmp_path):
        run_dir = str(tmp_path / "cli-run")
        self._run_cli("--run-dir", run_dir, "create", "--initial", '{"environment":"prod"}')

        result = self._run_cli("--run-dir", run_dir, "get", "environment")
        assert result.returncode == 0
        assert result.stdout.strip() == "prod"

        result = self._run_cli("--run-dir", run_dir, "put", "application.release", "rhoai-3.5")
        assert result.returncode == 0

        result = self._run_cli("--run-dir", run_dir, "get", "application.release")
        assert result.returncode == 0
        assert result.stdout.strip() == "rhoai-3.5"

    def test_get_missing_key_fails(self, tmp_path):
        run_dir = str(tmp_path / "cli-run")
        self._run_cli("--run-dir", run_dir, "create")
        result = self._run_cli("--run-dir", run_dir, "get", "nonexistent.key")
        assert result.returncode == 1
