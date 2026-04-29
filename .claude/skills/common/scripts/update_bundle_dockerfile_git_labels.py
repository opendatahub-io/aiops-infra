#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Add git-url and git-commit ARG declarations and LABEL entries to a bundle Dockerfile.

Usage:
  uv run --script update_bundle_dockerfile_git_labels.py <dockerfile> \
    --component-name <component-name>

Derives:
  GIT_URL_LABEL    = <COMPONENT_NAME_UPPER>_GIT_URL
  GIT_COMMIT_LABEL = <COMPONENT_NAME_UPPER>_GIT_COMMIT

Modifies the Dockerfile in place (idempotent):
  1. Appends ARG <GIT_URL_LABEL>= and ARG <GIT_COMMIT_LABEL>= after the last
     existing ARG declaration.
  2. Inserts <component>.git.url="${GIT_URL_LABEL}" and
     <component>.git.commit="${GIT_COMMIT_LABEL}" after the last existing
     .git.url= / .git.commit= LABEL entry, adding a continuation backslash
     to the previously-last entry when needed.

Outputs (stdout, for eval):
  GIT_URL_LABEL=<value>
  GIT_COMMIT_LABEL=<value>

Status messages go to stderr.

Exit 0: success (modified or already up-to-date).
Exit 1: unrecoverable error.
"""
import argparse
import sys
from pathlib import Path


def derive_label_vars(component_name: str) -> tuple[str, str]:
    upper = component_name.upper().replace("-", "_")
    return f"{upper}_GIT_URL", f"{upper}_GIT_COMMIT"


def update_arg_declarations(lines: list[str], url_label: str, commit_label: str) -> tuple[list[str], bool]:
    url_arg = f"ARG {url_label}=\n"
    if url_arg in lines:
        print(f"ARG {url_label} already present — skipping ARG declarations.", file=sys.stderr)
        return lines, False

    last_arg = max((i for i, l in enumerate(lines) if l.startswith("ARG ")), default=None)
    new_args = [f"ARG {url_label}=\n", f"ARG {commit_label}=\n"]
    if last_arg is not None:
        for j, a in enumerate(new_args):
            lines.insert(last_arg + 1 + j, a)
    else:
        lines.extend(new_args)
    return lines, True


def update_label_entries(lines: list[str], component: str, url_label: str, commit_label: str) -> tuple[list[str], bool]:
    url_prefix = f"{component}.git.url="
    if any(url_prefix in l for l in lines):
        print(f"{component}.git.url label already present — skipping LABEL entries.", file=sys.stderr)
        return lines, False

    url_value = f"${{{url_label}}}"
    commit_value = f"${{{commit_label}}}"

    last_label_idx = None
    label_indent = "    "
    for i, line in enumerate(lines):
        if ".git.url=" in line or ".git.commit=" in line:
            last_label_idx = i
            label_indent = line[: len(line) - len(line.lstrip())]

    if last_label_idx is not None:
        stripped = lines[last_label_idx].rstrip()
        if not stripped.endswith("\\"):
            lines[last_label_idx] = stripped + " \\\n"
        lines.insert(last_label_idx + 1, f'{label_indent}{component}.git.url="{url_value}" \\\n')
        lines.insert(last_label_idx + 2, f'{label_indent}{component}.git.commit="{commit_value}"\n')
    else:
        lines.append(f'    {component}.git.url="{url_value}" \\\n')
        lines.append(f'    {component}.git.commit="{commit_value}"\n')

    return lines, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dockerfile")
    parser.add_argument("--component-name", required=True)
    args = parser.parse_args()

    path = Path(args.dockerfile)
    if not path.exists():
        print(f"ERROR: Dockerfile not found: {path}", file=sys.stderr)
        sys.exit(1)

    url_label, commit_label = derive_label_vars(args.component_name)

    lines = path.read_text().splitlines(keepends=True)
    lines, arg_changed   = update_arg_declarations(lines, url_label, commit_label)
    lines, label_changed = update_label_entries(lines, args.component_name, url_label, commit_label)

    if arg_changed or label_changed:
        path.write_text("".join(lines))
        parts = []
        if arg_changed:
            parts.append("ARG declarations added")
        if label_changed:
            parts.append("LABEL entries added")
        print(f"Updated {path}: {', '.join(parts)}.", file=sys.stderr)

        new_content = path.read_text()
        errors = []
        if arg_changed and f"ARG {url_label}=" not in new_content:
            errors.append(f"ARG {url_label} not found after insert")
        if label_changed and f"{args.component_name}.git.url=" not in new_content:
            errors.append(f"{args.component_name}.git.url not found after insert")
        if errors:
            for e in errors:
                print(f"ERROR: Verification failed — {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("bundle/Dockerfile already up-to-date — no changes made.", file=sys.stderr)

    # Emit variable assignments for eval
    print(f"GIT_URL_LABEL={url_label}")
    print(f"GIT_COMMIT_LABEL={commit_label}")


if __name__ == "__main__":
    main()
