"""Initialize a conforma workflow run.

Creates a timestamped run directory under the conforma work directory,
writes the user's query and any --set key-value pairs to context.yaml,
and sets the .conforma-active symlink.

This is the single entry point for user input in conforma workflows.
All subsequent workflow steps read their parameters from context.yaml.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from _repo_root import REPO_ROOT  # noqa: E402

import conforma_context_ops  # noqa: E402


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
        help="Store an extra key-value pair in context.yaml (repeatable)",
    )
    args = parser.parse_args()

    work_dir = conforma_context_ops.discover_work_dir()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = work_dir / ts

    initial: dict = {
        "aiops_infra_root": str(REPO_ROOT),
        "user_query": args.query,
    }
    for key, value in args.extra:
        initial[key] = value

    conforma_context_ops.create(run_dir, initial)
    conforma_context_ops.set_active(run_dir)
    conforma_context_ops.install_wrapper(REPO_ROOT)

    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
