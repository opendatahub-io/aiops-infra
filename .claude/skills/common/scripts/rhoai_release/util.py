"""Common utilities: version parsing, text replacement, and git helpers."""

import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

# Optional: use GitPython if available, else subprocess for git
try:
    from git import Repo
    from git.exc import GitCommandError

    GITPYTHON_AVAILABLE = True
except ImportError:
    GITPYTHON_AVAILABLE = False
    Repo = None  # type: ignore
    GitCommandError = Exception  # type: ignore


def is_ea_version(version: str) -> bool:
    """Return True if version contains an EA suffix (.ea. or -ea. format)."""
    return ".ea." in version or "-ea." in version


def base_minor_version(version: str) -> str:
    """Return the X.Y part of a version, stripping any EA suffix.

    Handles both dot-separated (.ea.) and dash-separated (-ea.) EA formats.

    Examples:
        "3.5.ea.1" -> "3.5"
        "3.5-ea.1" -> "3.5"
        "3.5"      -> "3.5"
    """
    if ".ea." in version:
        return version.split(".ea.")[0]
    if "-ea." in version:
        return version.split("-ea.")[0]
    return version


def parse_version_input(label: str) -> Tuple[str, str, str]:
    """
    Derive version, version_dash, and minor_dir from user input.
    Accepts e.g. "rhoai-3.4", "rhoai-3.5", "rhoai-3.4.ea.1", "rhoai-3.4.ea.2", "3.4", etc.
    For EA (e.g. 3.4.ea.1, 3.4.ea.2):
      - version_dash = "3-4-ea-1" / "3-4-ea-2" (all dashes) for K8s identifiers and RPA file names.
      - minor_dir = "v3.4-ea.1" / "v3.4-ea.2" (hyphen before ea.N) for folder and tenant file names only.
    Returns (version, version_dash, minor_dir).
    """
    s = label.strip()
    if s.lower().startswith("rhoai-"):
        s = s[6:].strip()  # strip "rhoai-" prefix
    version = s
    if ".ea." in s:
        # Identifiers and RPA filenames use all-dashes (v3-4-ea-1, v3-4-ea-2) like v3.4-ea.1 in konflux-release-data.
        version_dash = s.replace(".", "-")  # 3.4.ea.1 -> 3-4-ea-1, 3.4.ea.2 -> 3-4-ea-2
        # Folder and tenant file names use hyphen before ea.N: v3.4-ea.1, v3.4-ea.2
        minor_dir = "v" + s.replace(".ea.", "-ea.")  # e.g. v3.4-ea.1, v3.4-ea.2
    else:
        version_dash = s.replace(".", "-")
        minor_dir = "v" + version
    return version, version_dash, minor_dir


def run_git_cmd(cwd: Path, *args: str) -> str:
    """Run a git command via subprocess. Returns stdout or raises on failure."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Git command failed: git {' '.join(args)}\nstderr: {result.stderr}"
        )
    return (result.stdout or "").strip()


def replace_version_safe(content: str, old: str, new: str) -> str:
    """Replace old version string with new using word boundaries to avoid partial matches."""
    if not old:
        return content
    pattern = r"\b" + re.escape(old) + r"\b"
    return re.sub(pattern, new, content)


def replace_v_version_dash(content: str, old_dash: str, new_dash: str) -> str:
    """Replace vX-Y (e.g. v3-4 or v3-4-ea-1) with new dashed form. For standard version skip v3-4-ea-*."""
    if not old_dash:
        return content
    old_v = "v" + old_dash
    new_v = "v" + new_dash
    # When old_dash is "3-4-ea-1" we want to match "v3-4-ea-1"; when "3-4" we must not match "v3-4-ea-1"
    if "-ea-" in old_dash:
        pattern = r"\b" + re.escape(old_v) + r"\b"
    else:
        pattern = r"\b" + re.escape(old_v) + r"(?!-ea)"
    return re.sub(pattern, new_v, content)


def replace_v_version_dotted(content: str, old_version: str, new_version: str) -> str:
    """Replace vX.Y (e.g. v3.4 in filenames) with vX.Y (e.g. v3.5). Skip v3.4.ea.N and v3.4-ea.N."""
    if not old_version:
        return content
    old_v = "v" + old_version
    new_v = "v" + new_version
    # Do not match when followed by .ea or -ea (EA version suffix)
    pattern = r"\b" + re.escape(old_v) + r"(?!\.ea)(?!-ea)"
    return re.sub(pattern, new_v, content)


def apply_version_replacements(
    content: str,
    previous_version: str,
    new_version: str,
    previous_version_dash: str,
    new_version_dash: str,
    previous_ea_display: Optional[str] = None,
    new_ea_display: Optional[str] = None,
) -> str:
    """
    Apply all version replacements (dotted, dashed, vX-Y, vX.Y).
    For EA, pass previous_ea_display/new_ea_display (e.g. "3.4-ea.1", "3.4-ea.2") to fix
    display values and branch/version fields to match v3.4-ea.1 style (hyphen before ea.N).
    """
    content = replace_version_safe(content, previous_version, new_version)
    content = replace_version_safe(content, previous_version_dash, new_version_dash)
    content = replace_v_version_dash(content, previous_version_dash, new_version_dash)
    content = replace_v_version_dotted(content, previous_version, new_version)
    if previous_ea_display and new_ea_display:
        content = replace_version_safe(content, previous_ea_display, new_ea_display)
        content = replace_version_safe(content, f"v{previous_ea_display}", f"v{new_ea_display}")
        content = replace_version_safe(content, f"rhoai-{previous_ea_display}", f"rhoai-{new_ea_display}")
    return content
