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


class TestDetectAiModel:
    """Tests for auto-detecting the LLM model from the environment."""

    def _clear_model_env(self, monkeypatch):
        for env_var in init_conforma_run.AI_MODEL_ENV_VARS:
            monkeypatch.delenv(env_var, raising=False)

    def test_returns_ai_model_env(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("AI_MODEL", "claude-opus-4-5")
        assert init_conforma_run.detect_ai_model() == "claude-opus-4-5"

    def test_falls_back_to_anthropic_model(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        assert init_conforma_run.detect_ai_model() == "claude-sonnet-4-5"

    def test_falls_back_to_claude_model(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-4-5")
        assert init_conforma_run.detect_ai_model() == "claude-haiku-4-5"

    def test_priority_ai_model_over_others(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("AI_MODEL", "model-a")
        monkeypatch.setenv("ANTHROPIC_MODEL", "model-b")
        monkeypatch.setenv("CLAUDE_MODEL", "model-c")
        assert init_conforma_run.detect_ai_model() == "model-a"

    def test_priority_anthropic_over_claude(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_MODEL", "model-b")
        monkeypatch.setenv("CLAUDE_MODEL", "model-c")
        assert init_conforma_run.detect_ai_model() == "model-b"

    def test_returns_empty_when_no_env_set(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        assert init_conforma_run.detect_ai_model() == ""

    def test_strips_surrounding_whitespace(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("AI_MODEL", "  claude-sonnet-4-5  ")
        assert init_conforma_run.detect_ai_model() == "claude-sonnet-4-5"

    def test_whitespace_only_ai_model_falls_through(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("AI_MODEL", "   ")
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        assert init_conforma_run.detect_ai_model() == "claude-sonnet-4-5"


class TestAiModelContextPersistence:
    """Tests for persisting the LLM model name into context.yaml."""

    @staticmethod
    def _context_data(tmp_path):
        runs = [d for d in tmp_path.iterdir() if d.is_dir() and not d.is_symlink()]
        assert len(runs) == 1
        return yaml.safe_load((runs[0] / "context.yaml").read_text())

    def test_ai_model_from_env_stored_in_context(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        for env_var in ("ANTHROPIC_MODEL", "CLAUDE_MODEL"):
            monkeypatch.delenv(env_var, raising=False)
        monkeypatch.setenv("AI_MODEL", "claude-sonnet-4-5")
        monkeypatch.setattr("sys.argv", ["init_conforma_run.py", "rhoai-3.5ea2"])
        with patch.object(init_conforma_run, "REPO_ROOT", tmp_path / "repo"):
            init_conforma_run.main()

        data = self._context_data(tmp_path)
        assert data["ai_model"] == "claude-sonnet-4-5"

    def test_set_ai_model_overrides_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        for env_var in ("ANTHROPIC_MODEL", "CLAUDE_MODEL"):
            monkeypatch.delenv(env_var, raising=False)
        monkeypatch.setenv("AI_MODEL", "env-model")
        monkeypatch.setattr("sys.argv", [
            "init_conforma_run.py", "rhoai-3.5ea2",
            "--set", "ai_model", "explicit-model",
        ])
        with patch.object(init_conforma_run, "REPO_ROOT", tmp_path / "repo"):
            init_conforma_run.main()

        data = self._context_data(tmp_path)
        assert data["ai_model"] == "explicit-model"

    def test_ai_model_absent_when_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        for env_var in init_conforma_run.AI_MODEL_ENV_VARS:
            monkeypatch.delenv(env_var, raising=False)
        monkeypatch.setattr("sys.argv", ["init_conforma_run.py", "rhoai-3.5ea2"])
        with patch.object(init_conforma_run, "REPO_ROOT", tmp_path / "repo"):
            init_conforma_run.main()

        data = self._context_data(tmp_path)
        assert "ai_model" not in data

