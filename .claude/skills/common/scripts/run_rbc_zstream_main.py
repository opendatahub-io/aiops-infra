#!/usr/bin/env python3
"""
Wrapper for RBC Z-Stream Main step.

Invokes the rbc_zstream_main.py script from rhoai-release-onboarding repository.
Auto-discovers the repository location and handles environment setup.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

import os
import subprocess
import sys
from pathlib import Path


def find_rhoai_release_dir() -> Path:
    """Search for rhoai-release-onboarding in common locations."""
    # Try environment variable first
    env_path = os.getenv("RHOAI_RELEASE_ONBOARDING_DIR")
    if env_path:
        path = Path(env_path)
        if path.exists() and (path / "src").exists():
            return path

    # Search common locations
    search_paths = [
        Path.cwd().parent / "rhoai-release-onboarding",
        Path.cwd().parent.parent / "rhoai-release-onboarding",
        Path.home() / "Documents/rhoai/rhoai-repos/rhoai-release-onboarding",
        Path.home() / "rhoai-release-onboarding",
        Path("/opt/rhoai-release-onboarding"),
    ]

    for path in search_paths:
        if path.exists() and (path / "src").exists():
            return path

    raise FileNotFoundError(
        "rhoai-release-onboarding directory not found. "
        "Set RHOAI_RELEASE_ONBOARDING_DIR environment variable or ensure "
        "rhoai-release-onboarding is in a standard location."
    )


def main():
    try:
        rhoai_release_dir = find_rhoai_release_dir()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Use venv Python if available, otherwise system Python
    venv_python = rhoai_release_dir / ".venv" / "bin" / "python"
    python_cmd = str(venv_python) if venv_python.exists() else "python"

    # Build command
    cmd = [python_cmd, "-m", "src.rbc_zstream_main"] + sys.argv[1:]

    # Execute in rhoai-release-onboarding directory
    result = subprocess.run(cmd, cwd=rhoai_release_dir)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
