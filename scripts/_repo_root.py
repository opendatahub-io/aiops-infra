"""Shared repo-root resolver for scripts/ modules.

Provides ``REPO_ROOT`` — the absolute path to the aiops-infra repository root.

Resolution order:
1. Walk up from ``__file__`` checking for ``pyproject.toml`` (in-repo execution)
2. Read ``aiops_infra_root`` from ``~/.conforma/.conforma-active/context.yaml``
3. ``AIOPS_INFRA_ROOT`` environment variable
4. ``~/.local/share/aiops-infra`` fallback

Import at the top of any repo-root script::

    from _repo_root import REPO_ROOT
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_repo_root() -> Path:
    here = Path(__file__).resolve().parent
    candidate = here.parent
    if (candidate / "pyproject.toml").is_file():
        return candidate

    ctx_path = Path.home() / ".conforma" / ".conforma-active" / "context.yaml"
    if ctx_path.is_file():
        try:
            import yaml

            ctx = yaml.safe_load(ctx_path.read_text(encoding="utf-8"))
            if ctx and "aiops_infra_root" in ctx:
                p = Path(os.path.expanduser(str(ctx["aiops_infra_root"])))
                if (p / "pyproject.toml").is_file():
                    return p
        except Exception:
            pass

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
        "ensure pyproject.toml exists in the parent of this file's directory."
    )


def _bootstrap() -> Path:
    root = _find_repo_root()
    scripts_dir = str(root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(1, scripts_dir)
    return root


REPO_ROOT = _bootstrap()
