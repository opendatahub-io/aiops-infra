"""conforma_context_ops.py -- Central run-context management for conforma workflows (dual-mode: CLI + importable).

Each conforma run stores its parameters and step outputs in a ``context.yaml``
file inside a timestamped directory under ``~/.conforma/``.  This module
manages reads, writes, discovery, and validation of that file.

Usage (importable)::

    import conforma_context_ops as ctx

    work_dir = ctx.discover_work_dir()
    run_dir  = ctx.discover_run_dir()
    context  = ctx.load(run_dir)
    release  = ctx.get(run_dir, "application.release")

Usage (CLI)::

    python conforma_context_ops.py show
    python conforma_context_ops.py get application.release
    python conforma_context_ops.py put steps.fetch.status completed
    python conforma_context_ops.py create --initial '{"environment":"prod"}'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

CONTEXT_FILENAME = "context.yaml"
ACTIVE_LINK = ".conforma-active"
DEFAULT_WORK_DIR = Path.home() / ".conforma"

_SENTINEL = object()

_PATH_FIELDS: set[tuple[str, ...]] = {
    ("run", "run_dir"),
    ("steps", "coverage", "clone_dir"),
}


def contract_home(path: Path) -> str:
    """Contract an absolute path so it starts with ``~/`` when under $HOME."""
    try:
        relative = path.relative_to(Path.home())
        return "~/" + str(relative)
    except ValueError:
        return str(path)


def expand_home(path_str: str) -> Path:
    """Expand ``~`` at the start of a path string to the real home directory."""
    return Path(os.path.expanduser(path_str))


def _expand_path_fields(data: dict) -> dict:
    """Walk *data* and expand ``~`` in all known path-valued fields."""
    for field_path in _PATH_FIELDS:
        node = data
        for key in field_path[:-1]:
            if not isinstance(node, dict) or key not in node:
                break
            node = node[key]
        else:
            last = field_path[-1]
            if isinstance(node, dict) and last in node and isinstance(node[last], str):
                node[last] = str(expand_home(node[last]))
    return data


def _contract_path_fields(data: dict) -> dict:
    """Walk *data* and contract ``$HOME`` to ``~`` in all known path-valued fields."""
    for field_path in _PATH_FIELDS:
        node = data
        for key in field_path[:-1]:
            if not isinstance(node, dict) or key not in node:
                break
            node = node[key]
        else:
            last = field_path[-1]
            if isinstance(node, dict) and last in node and isinstance(node[last], str):
                node[last] = contract_home(Path(node[last]))
    return data


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_work_dir() -> Path:
    """Return the conforma work directory, creating it if needed.

    Resolution order:
    1. ``CONFORMA_WORKDIR`` environment variable
    2. ``~/.conforma/``
    """
    env = os.environ.get("CONFORMA_WORKDIR")
    if env:
        work = Path(env)
    else:
        work = DEFAULT_WORK_DIR
    work.mkdir(parents=True, exist_ok=True)
    return work


def discover_run_dir(explicit: Path | str | None = None) -> Path:
    """Return the active run directory.

    Resolution order:
    1. *explicit* argument (from ``--run-dir``)
    2. ``.conforma-active`` symlink in the work directory
    3. Raise with a clear message

    The returned path is guaranteed to contain ``context.yaml``.
    """
    if explicit is not None:
        run_dir = Path(explicit)
        ctx_file = run_dir / CONTEXT_FILENAME
        if not ctx_file.is_file():
            raise FileNotFoundError(
                f"No {CONTEXT_FILENAME} in {run_dir}\n"
                f"Run resolve_release_context.py first to create a run context."
            )
        return run_dir

    work = discover_work_dir()
    link = work / ACTIVE_LINK
    if not link.exists():
        raise FileNotFoundError(
            f"No active conforma run.\n"
            f"  No --run-dir argument and {link} does not exist.\n"
            f"  Run resolve_release_context.py first to create a run context."
        )
    if not link.is_dir():
        raise FileNotFoundError(
            f"{link} exists but is not a valid symlink to a directory.\n"
            f"  Remove it and run resolve_release_context.py to recreate."
        )
    run_dir = link.resolve()
    ctx_file = run_dir / CONTEXT_FILENAME
    if not ctx_file.is_file():
        raise FileNotFoundError(
            f"{link} -> {run_dir} but no {CONTEXT_FILENAME} found there.\n"
            f"  Run resolve_release_context.py to create a valid run context."
        )
    return run_dir


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def _context_path(run_dir: Path) -> Path:
    return run_dir / CONTEXT_FILENAME


def _atomic_write(path: Path, data: dict) -> None:
    """Write *data* as YAML to *path* atomically via temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def create(run_dir: Path, initial: dict | None = None) -> dict:
    """Create a new ``context.yaml`` in *run_dir* with *initial* values.

    Adds ``run.created_at`` and ``run.run_dir`` automatically.
    Returns the written context dict (with ``~`` paths — not expanded).
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    data: dict = initial.copy() if initial else {}

    run_section = data.setdefault("run", {})
    run_section.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    run_section["run_dir"] = contract_home(run_dir.resolve())

    data.setdefault("steps", {})

    _contract_path_fields(data)
    _atomic_write(_context_path(run_dir), data)
    return data


def load(run_dir: Path) -> dict:
    """Load and return the run context, with ``~`` expanded in path fields."""
    path = _context_path(run_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Context file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _expand_path_fields(data)


def get(run_dir: Path, dotted_key: str, default: Any = _SENTINEL) -> Any:
    """Read a dotted key (e.g. ``application.release``) from the context.

    Raises ``KeyError`` if the key is missing and no *default* is given.
    """
    data = load(run_dir)
    keys = dotted_key.split(".")
    node: Any = data
    for i, key in enumerate(keys):
        if not isinstance(node, dict) or key not in node:
            if default is not _SENTINEL:
                return default
            traversed = ".".join(keys[: i + 1])
            raise KeyError(
                f"Key '{traversed}' not found in {_context_path(run_dir)}"
            )
        node = node[key]
    return node


def put(run_dir: Path, dotted_key: str, value: Any) -> dict:
    """Set a dotted key and write back.  Returns the updated context."""
    data = load(run_dir)
    keys = dotted_key.split(".")
    node = data
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    _contract_path_fields(data)
    _atomic_write(_context_path(run_dir), data)
    return _expand_path_fields(data)


def update_step(run_dir: Path, step_name: str, status: str, **outputs: Any) -> dict:
    """Update a step's status and output file paths.

    Returns the updated context.
    """
    data = load(run_dir)
    steps = data.setdefault("steps", {})
    step = steps.setdefault(step_name, {})
    step["status"] = status
    if status == "completed":
        step["completed_at"] = datetime.now(timezone.utc).isoformat()
    for k, v in outputs.items():
        step[k] = v
    _contract_path_fields(data)
    _atomic_write(_context_path(run_dir), data)
    return _expand_path_fields(data)


def require(run_dir: Path, *dotted_keys: str) -> dict:
    """Assert all *dotted_keys* exist in the context.

    Returns the loaded context on success.  Raises ``KeyError`` listing all
    missing keys on failure.
    """
    data = load(run_dir)
    missing: list[str] = []
    for dk in dotted_keys:
        keys = dk.split(".")
        node: Any = data
        found = True
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                found = False
                break
            node = node[key]
        if not found:
            missing.append(dk)
    if missing:
        raise KeyError(
            f"Missing required keys in {_context_path(run_dir)}: "
            + ", ".join(missing)
        )
    return data


def resolve_arg(
    args: Any,
    arg_name: str,
    context: dict | None,
    context_key: str,
) -> Any:
    """Return the value from *args* if set, else from *context*.

    ``args`` is an ``argparse.Namespace`` (or any object with attributes).
    *arg_name* is the attribute name on *args* (underscored, e.g. ``release``).
    *context_key* is a dotted key into *context* (e.g. ``application.release``).

    Raises ``SystemExit`` with a clear message if neither source has a value.
    """
    cli_val = getattr(args, arg_name, None)
    if cli_val is not None:
        return cli_val

    if context is not None:
        keys = context_key.split(".")
        node: Any = context
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if node is not None:
            return node

    print(
        f"Error: --{arg_name.replace('_', '-')} not provided and "
        f"'{context_key}' not found in context.\n"
        f"  Either pass --{arg_name.replace('_', '-')} explicitly or "
        f"ensure the run context contains '{context_key}'.",
        file=sys.stderr,
    )
    sys.exit(1)


def set_active(run_dir: Path) -> None:
    """Point the ``.conforma-active`` symlink to *run_dir*."""
    work = discover_work_dir()
    link = work / ACTIVE_LINK
    target = run_dir.resolve()
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)


def install_wrapper(repo_root: Path) -> bool:
    """Install or refresh ``~/.conforma/bin/conforma_run.sh`` from the repo template.

    Returns True if the wrapper was installed/updated, False if already current.
    """
    template = repo_root / "scripts" / "conforma_run.sh.tpl"
    if not template.is_file():
        return False

    bin_dir = discover_work_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "conforma_run.sh"

    template_content = template.read_bytes()
    if target.is_file() and target.read_bytes() == template_content:
        return False

    target.write_bytes(template_content)
    target.chmod(0o755)
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage conforma run context files."
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Path to the run directory. Auto-discovered via .conforma-active if omitted.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub_create = sub.add_parser("create", help="Create a new run context")
    sub_create.add_argument(
        "--initial", default=None, help="JSON string with initial values"
    )

    sub_show = sub.add_parser("show", help="Show the full context")

    sub_get = sub.add_parser("get", help="Get a dotted key from the context")
    sub_get.add_argument("key", help="Dotted key (e.g. application.release)")

    sub_put = sub.add_parser("put", help="Set a dotted key in the context")
    sub_put.add_argument("key", help="Dotted key (e.g. steps.fetch.status)")
    sub_put.add_argument("value", help="Value to set")

    args = parser.parse_args()

    if args.command == "create":
        run_dir = Path(args.run_dir) if args.run_dir else None
        if run_dir is None:
            work = discover_work_dir()
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            run_dir = work / timestamp
        initial = json.loads(args.initial) if args.initial else None
        ctx = create(run_dir, initial)
        print(f"Created: {run_dir / CONTEXT_FILENAME}")
        json.dump(ctx, sys.stdout, indent=2)
        print()
        return 0

    run_dir = discover_run_dir(args.run_dir)

    if args.command == "show":
        ctx = load(run_dir)
        yaml.dump(ctx, sys.stdout, default_flow_style=False, sort_keys=False)
        return 0

    if args.command == "get":
        try:
            val = get(run_dir, args.key)
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if isinstance(val, (dict, list)):
            json.dump(val, sys.stdout, indent=2)
            print()
        else:
            print(val)
        return 0

    if args.command == "put":
        value: Any = args.value
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        else:
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
        put(run_dir, args.key, value)
        print(f"Set {args.key}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
