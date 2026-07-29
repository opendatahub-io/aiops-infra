"""Tests for scripts/conforma_run.sh.tpl wrapper."""

from __future__ import annotations

import os
import subprocess

from _repo_root import REPO_ROOT

WRAPPER = REPO_ROOT / "scripts" / "conforma_run.sh.tpl"


def _run(args, env=None, cwd=None):
    """Run the wrapper with given args, return CompletedProcess."""
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(WRAPPER), *args],
        capture_output=True,
        text=True,
        env=merged_env,
        cwd=cwd or str(REPO_ROOT),
    )


class TestHelp:
    def test_help_flag(self):
        result = _run(["--help"])
        assert result.returncode == 0
        assert "Usage:" in result.stdout
        assert "Resolution chain" in result.stdout

    def test_h_flag(self):
        result = _run(["-h"])
        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_help_lists_available_scripts(self):
        result = _run(["--help"])
        assert result.returncode == 0
        assert "Available top-level scripts:" in result.stdout
        assert "conforma_context_ops.py" in result.stdout


class TestVersion:
    def test_version_prints_hash(self):
        result = _run(["--version"])
        assert result.returncode == 0
        version = result.stdout.strip()
        assert len(version) == 32
        assert all(c in "0123456789abcdef" for c in version)


class TestNoArgs:
    def test_no_args_error(self):
        result = _run([])
        assert result.returncode == 1
        assert "No script path" in result.stderr


class TestScriptNotFound:
    def test_nonexistent_script(self):
        result = _run(
            ["scripts/nonexistent.py"],
            env={"AIOPS_INFRA_ROOT": str(REPO_ROOT)},
        )
        assert result.returncode == 1
        assert "Script not found" in result.stderr


class TestRepoRootResolution:
    def test_env_var_resolution(self, tmp_path):
        script = tmp_path / "scripts" / "hello.py"
        script.parent.mkdir()
        script.write_text('print("hello")\n')
        (tmp_path / "pyproject.toml").write_text("[project]\n")

        env = {
            "AIOPS_INFRA_ROOT": str(tmp_path),
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
            "GIT_CEILING_DIRECTORIES": str(tmp_path),
        }
        result = _run(["scripts/hello.py"], env=env, cwd=str(tmp_path))
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_context_yaml_resolution(self, tmp_path, monkeypatch):
        conforma_dir = tmp_path / ".conforma"
        active = conforma_dir / ".conforma-active"
        run_dir = conforma_dir / "run1"
        run_dir.mkdir(parents=True)
        active.symlink_to(run_dir)

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[project]\n")
        script = repo / "scripts" / "hello.py"
        script.parent.mkdir()
        script.write_text('print("hello-from-ctx")\n')

        (run_dir / "context.yaml").write_text(
            f"aiops_infra_root: {repo}\n"
        )

        env = {
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
        }
        result = _run(["scripts/hello.py"], env=env, cwd=str(tmp_path))
        assert result.returncode == 0
        assert "hello-from-ctx" in result.stdout

    def test_git_fallback(self):
        result = _run(
            ["scripts/conforma_context_ops.py", "--help"],
            env={"AIOPS_INFRA_ROOT": ""},
        )
        assert result.returncode == 0

    def test_all_fallbacks_fail(self, tmp_path):
        env = {
            "HOME": str(tmp_path),
            "AIOPS_INFRA_ROOT": "",
            "PATH": os.environ.get("PATH", ""),
        }
        result = _run(
            ["scripts/hello.py"],
            env=env,
            cwd=str(tmp_path),
        )
        assert result.returncode == 1
        assert "Cannot find aiops-infra" in result.stderr


class TestPassthrough:
    def test_args_passed_through(self):
        result = _run(["scripts/conforma_context_ops.py", "--help"])
        assert result.returncode == 0
        assert "Manage conforma run context" in result.stdout

    def test_skills_path(self):
        result = _run(
            ["skills/conforma-analyze/scripts/analyze_csv_report.py", "--help"],
        )
        assert result.returncode == 0
