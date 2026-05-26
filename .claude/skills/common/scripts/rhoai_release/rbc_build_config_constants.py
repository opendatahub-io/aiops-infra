"""Non-secret defaults for RHOAI Build Config (GitHub) automation.

You only need ``GITHUB_TOKEN`` in a root ``.env`` file. All repo URLs and flags below are used unless you
override them via environment variables (optional).

Override via environment or ``.env``. Do not put real tokens in this file.
"""

import os


def env_or_default(name: str, default: str) -> str:
    """Use ``default`` if env var is unset, empty, or whitespace-only (avoids bad overrides from ``KEY=``)."""
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    return v


RBC_MAIN_REPO = "https://github.com/red-hat-data-services/RHOAI-Build-Config.git"

TEKTON_DIR = ".tekton"
BUNDLE_PATCH = "bundle/bundle-patch.yaml"
CSV_PATCH = "bundle/csv-patch.yaml"

# Appended to argv[2] to form the PR base branch name. Empty (default) = PR base is exactly argv[2] (e.g. rhoai-3.4).
# Set e.g. "-test" if your team uses rhoai-3.4-test. When the base branch is missing on origin, rbc_release creates
# it at the same commit as argv[1]. If argv[2] ends with this suffix, logical train = argv[2] without suffix.
RBC_STAGING_BRANCH_SUFFIX = ""

# PR head branch: prefix + train without leading "rhoai-" (e.g. automation-3.4, automation-3.4-ea.1).
RBC_AUTOMATION_BRANCH_PREFIX = "automation-"

# Legacy (ignored when RBC_AUTOMATION_BRANCH_PREFIX is used for release head).
RBC_BRANCH_PREFIX = ""
RBC_BRANCH_SUFFIX = "-automation"

# Abort commit if more than this many paths are staged (safety; normal run is ≤6).
RBC_MAX_STAGED_PATHS = "20"

# After commit, rebase automation branch onto latest PR base before push (reduces merge conflicts). Set "0" to skip.
RBC_REBASE_ONTO_LATEST = "1"

# When 1 (default) and GITHUB_TOKEN is set, use it in https:// Git URLs so ``git clone`` / ``fetch`` / ``push`` do not
# prompt (Git does not read ``.env`` by itself). Set to 0 to use only the OS credential helper / SSH.
RBC_GIT_USE_GITHUB_TOKEN = "1"

RBC_SKIP_CI = "1"
# Refuse to push PR base when it is missing on origin (release script only uses this for base-branch publish).
RBC_SKIP_PR_BASE_PUSH = ""
# Legacy name from fork workflow; ignored by current code (base is never force-synced on the product repo).
RBC_SKIP_FORK_BASE_SYNC = ""
RBC_SKIP_PROGRESSION_CHECK = ""

# ``rbc_release`` / ``rbc_main_onboard``: set to 1/true or use ``--dry-run`` — show changes only (no commit/push/PR).
RBC_DRY_RUN = ""

RBC_MAIN_HEAD_PREFIX = "main-onboard-"
MAIN_BRANCH = "main"

RBC_REPLACE_EXISTING_CATALOG = ""
RBC_REPLACE_EXISTING_TEKTON = ""
RBC_NO_ZSTREAM_RESET = ""
RBC_NO_AUTO_REPLACE_EA_TO_GA = ""
