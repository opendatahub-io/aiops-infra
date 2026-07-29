"""Tests for init_conforma_run.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import init_conforma_run


class TestInitConformaRun:
    def test_creates_run_dir_and_context(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["init_conforma_run.py", "rhoai-3.5ea2"])
        with patch.object(init_conforma_run, "REPO_ROOT", tmp_path / "repo"):
            ret = init_conforma_run.main()

        assert ret == 0
        runs = [d for d in tmp_path.iterdir() if d.is_dir() and not d.is_symlink()]
        assert len(runs) == 1
        context_file = runs[0] / "context.yaml"
        assert context_file.is_file()

    def test_user_query_stored(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["init_conforma_run.py", "rhoai-3.5ea2"])
        with patch.object(init_conforma_run, "REPO_ROOT", tmp_path / "repo"):
            init_conforma_run.main()

        runs = [d for d in tmp_path.iterdir() if d.is_dir()]
        data = yaml.safe_load((runs[0] / "context.yaml").read_text())
        assert data["user_query"] == "rhoai-3.5ea2"

    def test_set_pairs_stored(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr(
            "sys.argv",
            [
                "init_conforma_run.py",
                "rhoai-3.5ea2",
                "--set",
                "violation_code",
                "hermetic_task.hermetic",
                "--set",
                "custom_key",
                "custom_value",
            ],
        )
        with patch.object(init_conforma_run, "REPO_ROOT", tmp_path / "repo"):
            init_conforma_run.main()

        runs = [d for d in tmp_path.iterdir() if d.is_dir()]
        data = yaml.safe_load((runs[0] / "context.yaml").read_text())
        assert data["violation_code"] == "hermetic_task.hermetic"
        assert data["custom_key"] == "custom_value"

    def test_sets_active_symlink(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["init_conforma_run.py", "rhoai-3.5ea2"])
        with patch.object(init_conforma_run, "REPO_ROOT", tmp_path / "repo"):
            init_conforma_run.main()

        active_link = tmp_path / ".conforma-active"
        assert active_link.is_symlink()
        runs = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert active_link.resolve() == runs[0].resolve()

    def test_repo_root_in_context(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["init_conforma_run.py", "rhoai-3.5ea2"])
        fake_root = tmp_path / "my-repo"
        with patch.object(init_conforma_run, "REPO_ROOT", fake_root):
            init_conforma_run.main()

        runs = [d for d in tmp_path.iterdir() if d.is_dir()]
        data = yaml.safe_load((runs[0] / "context.yaml").read_text())
        assert data["aiops_infra_root"] == str(fake_root)

    def test_run_metadata_auto_populated(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["init_conforma_run.py", "rhoai-3.5ea2"])
        with patch.object(init_conforma_run, "REPO_ROOT", tmp_path / "repo"):
            init_conforma_run.main()

        runs = [d for d in tmp_path.iterdir() if d.is_dir()]
        data = yaml.safe_load((runs[0] / "context.yaml").read_text())
        assert "run" in data
        assert "created_at" in data["run"]
        assert "run_dir" in data["run"]

    def test_fails_without_query(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            with patch.object(sys, "argv", ["init_conforma_run.py"]):
                init_conforma_run.main()
        assert exc_info.value.code != 0

    def test_prints_run_dir_to_stdout(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["init_conforma_run.py", "rhoai-3.5ea2"])
        with patch.object(init_conforma_run, "REPO_ROOT", tmp_path / "repo"):
            init_conforma_run.main()

        captured = capsys.readouterr()
        printed_path = Path(captured.out.strip())
        assert printed_path.is_dir()
        assert (printed_path / "context.yaml").is_file()

    def test_installs_wrapper(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["init_conforma_run.py", "rhoai-3.5ea2"])
        fake_root = tmp_path / "repo"
        tpl = fake_root / "scripts" / "conforma_run.sh.tpl"
        tpl.parent.mkdir(parents=True)
        tpl.write_text("#!/bin/bash\necho wrapper\n")

        with patch.object(init_conforma_run, "REPO_ROOT", fake_root):
            init_conforma_run.main()

        wrapper = tmp_path / "bin" / "conforma_run.sh"
        assert wrapper.is_file()
        assert wrapper.read_text() == tpl.read_text()
