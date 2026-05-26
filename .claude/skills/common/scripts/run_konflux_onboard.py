#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "PyYAML>=6.0",
#     "GitPython>=3.1.0",
#     "python-dotenv>=1.0.0",
#     "python-gitlab>=3.0.0",
# ]
# ///
"""
Wrapper for Konflux Onboard step - updates konflux-release-data and creates GitLab MR.

Usage:
  run_konflux_onboard.py <previous_version> <new_version> [--repo-dir <dir>] [--dry-run]

Examples:
  run_konflux_onboard.py rhoai-3.4 rhoai-3.5 --dry-run
  run_konflux_onboard.py rhoai-3.4 rhoai-3.5-ea.1 --repo-dir konflux-release-data

Authentication:
  KONFLUX_REPO_TOKEN — required; GitLab personal access token

Exit codes:
  0  Success (MR created or dry-run completed)
  1  Error (validation, git, or API error)
"""

import sys
from pathlib import Path

# Add rhoai_release package to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR / "rhoai_release"))

# Import and run main from konflux_onboard
try:
    from konflux_onboard import main
    sys.exit(main())
except Exception as e:
    print(f"ERROR: Failed to run Konflux onboard: {e}", file=sys.stderr)
    sys.exit(1)
