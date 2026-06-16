"""Smoke test: every Python module on the test sys.path must import cleanly.

Catches broken imports, shadowing issues, and missing dependencies at CI time.
Only checks directories that conftest.py adds to sys.path (scripts/ + registered
skill script dirs), so it reflects the actual import resolution order.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

_SKILL_SCRIPT_DIRS = [
    REPO_ROOT / "skills" / "conforma-analyze" / "scripts",
    REPO_ROOT / "skills" / "conforma-exception" / "scripts",
    REPO_ROOT / "skills" / "conforma-report-fetch" / "scripts",
]


def _discover_modules() -> list[str]:
    """Find all importable .py modules from scripts/ and registered skill dirs."""
    modules = []
    dirs = [SCRIPTS_DIR] + [d for d in _SKILL_SCRIPT_DIRS if d.is_dir()]

    for d in dirs:
        for py in sorted(d.glob("*.py")):
            if py.name.startswith("_"):
                continue
            modules.append(py.stem)

    return sorted(set(modules))


_LEGACY_IGNORE_LIST = {
    line.strip().replace("scripts/", "").replace(".py", "")
    for line in (REPO_ROOT / "tests" / ".test-ignore-list").read_text().splitlines()
    if line.strip() and not line.startswith("#")
}


@pytest.mark.parametrize("module", _discover_modules())
def test_module_imports_cleanly(module):
    """Each module must be importable without errors.

    Legacy scripts on .test-ignore-list that fail due to missing third-party
    packages are skipped -- they have their own dependency management (uv script
    headers) and are exempt from the test requirement.
    """
    if module in sys.modules:
        del sys.modules[module]
    try:
        importlib.import_module(module)
    except (ModuleNotFoundError, ImportError) as exc:
        if module in _LEGACY_IGNORE_LIST:
            pytest.skip(f"legacy script, optional dep missing: {exc}")
        raise
