#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "PyYAML>=6.0",
#     "GitPython>=3.1.0",
#     "python-dotenv>=1.0.0",
#     "requests>=2.31.0",
# ]
# ///
"""
Wrapper for RBC Main Onboard step - onboards catalog + Tekton files on main branch.

Usage:
  run_rbc_main.py <previous_version> <new_version> [--dry-run]

Examples:
  run_rbc_main.py rhoai-3.4 rhoai-3.5 --dry-run
  run_rbc_main.py rhoai-3.4 rhoai-3.5-ea.1

Authentication:
  GITHUB_TOKEN — required; GitHub personal access token with repo scope

Exit codes:
  0  Success (PR created or dry-run completed)
  1  Error (validation, git, or API error)
"""

import sys
from pathlib import Path

# Add rhoai_release package to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR / "rhoai_release"))

# Import and run main from rbc_main_onboard
try:
    from rbc_main_onboard import main
    sys.exit(main())
except Exception as e:
    print(f"ERROR: Failed to run RBC main onboard: {e}", file=sys.stderr)
    sys.exit(1)
