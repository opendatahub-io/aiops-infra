"""Auto-bootstrap for conforma-exception skill scripts.

Adds the repo-root ``scripts/`` directory to ``sys.path`` so that shared
modules (``gitlab_ops``, ``jira_ops``, ``yaml_ops``, ``cli_runner`` (shared))
can be imported directly.

Also ensures Python dependencies declared in ``pyproject.toml`` are installed
(uses ``uv sync`` if available, falls back to ``pip install -e .``).

Import this module at the top of any skill script that needs shared ops::

    import _setup_env  # noqa: F401  (side-effect import)
    import gitlab_ops
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT: Path | None = None
_BOOTSTRAPPED = False


def _find_repo_root() -> Path:
    """Walk up from this file to find the repository root.

    Path from this file: scripts/ -> conforma-exception/ -> skills/ -> <repo>/
    """
    here = Path(__file__).resolve().parent
    candidate = here.parent.parent.parent
    if (candidate / "pyproject.toml").is_file():
        return candidate

    env_root = os.environ.get("AIOPS_INFRA_ROOT")
    if env_root:
        p = Path(env_root)
        if (p / "pyproject.toml").is_file():
            return p

    fallback = Path.home() / ".local" / "share" / "aiops-infra"
    if (fallback / "pyproject.toml").is_file():
        return fallback

    raise RuntimeError(
        "Cannot find aiops-infra repo root. Set AIOPS_INFRA_ROOT or "
        "ensure pyproject.toml exists 3 levels above this file."
    )


def _ensure_dependencies(repo_root: Path) -> None:
    """Install Python deps if shared modules are not yet importable."""
    try:
        importlib.import_module("gitlab")
        importlib.import_module("jira")
        importlib.import_module("requests")
        importlib.import_module("yaml")
        return
    except ImportError:
        pass

    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return

    if _try_uv_sync(repo_root):
        return
    _try_pip_install(repo_root)


def _try_uv_sync(repo_root: Path) -> bool:
    import shutil

    if not shutil.which("uv"):
        return False
    try:
        subprocess.run(
            ["uv", "sync"],
            cwd=repo_root,
            capture_output=True,
            timeout=120,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _try_pip_install(repo_root: Path) -> None:
    mtime_marker = repo_root / ".pip-install-mtime"
    pyproject_mtime = (repo_root / "pyproject.toml").stat().st_mtime
    if mtime_marker.is_file():
        try:
            cached = float(mtime_marker.read_text().strip())
            if cached >= pyproject_mtime:
                return
        except (ValueError, OSError):
            pass

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
            cwd=repo_root,
            capture_output=True,
            timeout=120,
        )
        mtime_marker.write_text(str(pyproject_mtime))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


def _load_site_config(root: Path) -> None:
    """Load site config to populate infra env vars if available."""
    try:
        import site_config

        site_config.load()
    except Exception:
        pass


def _bootstrap() -> Path:
    """One-time bootstrap: find root, ensure deps, add scripts/ to path."""
    global _REPO_ROOT, _BOOTSTRAPPED
    if _BOOTSTRAPPED and _REPO_ROOT is not None:
        return _REPO_ROOT

    root = _find_repo_root()
    _REPO_ROOT = root

    _ensure_dependencies(root)

    scripts_dir = str(root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(1, scripts_dir)

    _load_site_config(root)

    _BOOTSTRAPPED = True
    return root


REPO_ROOT = _bootstrap()
