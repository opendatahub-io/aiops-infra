"""Initialize a conforma workflow run.

Creates a timestamped run directory under the conforma work directory,
writes the user's query and any --set key-value pairs to context.yaml,
and sets the .conforma-active symlink.

This is the single entry point for user input in conforma workflows.
All subsequent workflow steps read their parameters from context.yaml.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from _repo_root import REPO_ROOT  # noqa: E402

import conforma_context_ops  # noqa: E402

# Environment variables checked (in order) to auto-detect the LLM model
# that is executing the conforma workflow, for the guide's metadata footer.
AI_MODEL_ENV_VARS = ("AI_MODEL", "ANTHROPIC_MODEL", "CLAUDE_MODEL")


def detect_ai_model() -> str:
    """Return the LLM model name from the environment, or "" if unknown.

    Checks the well-known model environment variables in order and
    returns the first non-empty value.
    """
    for env_var in AI_MODEL_ENV_VARS:
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize a conforma workflow run",
    )
    parser.add_argument(
        "query",
        help="User's raw input text (e.g. 'rhoai-3.5ea2', 'rhoai-3.5-ea.1 stage')",
    )
    parser.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("KEY", "VALUE"),
        default=[],
        dest="extra",
        help="Store an extra key-value pair in context.yaml (repeatable). "
        "Use 'ai_model' to override the auto-detected LLM model.",
    )
    args = parser.parse_args()

    work_dir = conforma_context_ops.discover_work_dir()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = work_dir / ts

    initial: dict = {
        "aiops_infra_root": str(REPO_ROOT),
        "user_query": args.query,
    }
    ai_model = ""
    for key, value in args.extra:
        initial[key] = value
        if key == "ai_model":
            ai_model = value
    if not ai_model:
        ai_model = detect_ai_model()
    if ai_model:
        initial["ai_model"] = ai_model

    conforma_context_ops.create(run_dir, initial)
    conforma_context_ops.set_active(run_dir)
    conforma_context_ops.install_wrapper(REPO_ROOT)

    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
