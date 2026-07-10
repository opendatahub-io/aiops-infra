#!/usr/bin/env python3
"""Fix broken relative paths in conforma workflow files.

After the decomposition refactoring split SKILL.md files into
router + workflows/ subdirectories, relative paths were not adjusted
for the extra directory depth. This script fixes them.

Also provides ``--rewrite-script-paths`` to anchor all ``python3 scripts/``
and ``python3 skills/`` invocations to the repo root via context.yaml.

Run from repo root:
    python3 scripts/fix_workflow_paths.py
    python3 scripts/fix_workflow_paths.py --rewrite-script-paths --dry-run
"""

import argparse
import re
import sys
from pathlib import Path

from _repo_root import REPO_ROOT
SKILLS_DIR = REPO_ROOT / "skills"
SHARED_REFS_DIR = SKILLS_DIR / "references"


def find_workflow_files():
    """Find all workflow .md files under skills/conforma-*/workflows/."""
    files = []
    for skill_dir in sorted(SKILLS_DIR.glob("conforma-*")):
        wf_dir = skill_dir / "workflows"
        if wf_dir.is_dir():
            files.extend(sorted(wf_dir.glob("*.md")))
    return files


def skill_dir_for(workflow_file):
    """Get the parent skill directory for a workflow file."""
    return workflow_file.parent.parent


def fix_readme_links(content, workflow_file):
    """Fix [README.md](README.md) -> [README.md](../README.md)."""
    fixes = []
    pattern = re.compile(r'\[README\.md\]\(README\.md\)')
    for match in pattern.finditer(content):
        target = skill_dir_for(workflow_file) / "README.md"
        if target.exists():
            fixes.append(("README link", match.start(), match.end()))
    if fixes:
        content = pattern.sub("[README.md](../README.md)", content)
    return content, fixes


def fix_shared_reference_links(content, workflow_file):
    """Fix ../references/X -> ../../references/X for shared references.

    Only fixes links where X exists in skills/references/ (shared) but
    NOT in skills/<skill>/references/ (skill-local).
    """
    fixes = []
    skill_refs_dir = skill_dir_for(workflow_file) / "references"
    pattern = re.compile(r'\]\(\.\./references/([^)]+)\)')

    def replace_if_shared(match):
        filename = match.group(1)
        shared_exists = (SHARED_REFS_DIR / filename).exists()
        local_exists = (skill_refs_dir / filename).exists()
        if shared_exists and not local_exists:
            fixes.append(("shared ref", filename))
            return f"](../../references/{filename})"
        return match.group(0)

    content = pattern.sub(replace_if_shared, content)
    return content, fixes


def fix_bare_reference_links(content, workflow_file):
    """Fix ](references/X) -> ](../references/X) for skill-local references.

    From workflows/, references/X resolves to workflows/references/X (wrong).
    The intended target is skills/<skill>/references/X.
    """
    fixes = []
    skill_refs_dir = skill_dir_for(workflow_file) / "references"
    pattern = re.compile(r'\]\(references/([^)]+)\)')

    def replace_if_exists(match):
        filename = match.group(1)
        if (skill_refs_dir / filename).exists():
            fixes.append(("local ref", filename))
            return f"](../references/{filename})"
        return match.group(0)

    content = pattern.sub(replace_if_exists, content)
    return content, fixes


def fix_router_skill_md(dry_run):
    """Fix the conforma router SKILL.md broken link and ambiguous routing."""
    router = SKILLS_DIR / "conforma" / "SKILL.md"
    if not router.exists():
        print(f"  SKIP: {router.relative_to(REPO_ROOT)} not found")
        return 0

    content = router.read_text()
    original = content
    fixes = []

    old_link = "](references/violation-catalog.yaml)"
    new_link = "](../references/violation-catalog.yaml)"
    if old_link in content:
        content = content.replace(old_link, new_link)
        fixes.append("violation-catalog.yaml link href")

    old_routing = (
        "**read its SKILL.md** at `skills/<skill-name>/SKILL.md` "
        "(e.g. `skills/conforma-analyze/SKILL.md`)"
    )
    new_routing = (
        "**read its SKILL.md** (from the repository root) at "
        "`skills/<skill-name>/SKILL.md` "
        "(e.g. `skills/conforma-analyze/SKILL.md`)"
    )
    if old_routing in content:
        content = content.replace(old_routing, new_routing)
        fixes.append("routing instruction anchored to repo root")

    if content != original:
        rel = router.relative_to(REPO_ROOT)
        for f in fixes:
            print(f"  FIX [{rel}]: {f}")
        if not dry_run:
            router.write_text(content)
        return len(fixes)
    return 0


def verify_all_links(files):
    """Verify all markdown link hrefs in workflow files resolve to existing files."""
    errors = []
    link_pattern = re.compile(r'\]\(([^)]+)\)')

    for f in files:
        content = f.read_text()
        for match in link_pattern.finditer(content):
            href = match.group(1)
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if "$" in href or href in ("url",):
                continue
            resolved = (f.parent / href).resolve()
            if not resolved.exists():
                line_num = content[:match.start()].count("\n") + 1
                errors.append((f.relative_to(REPO_ROOT), line_num, href))

    return errors


_REPO_PREFIX = '_R="$(grep \'^aiops_infra_root:\' ~/.conforma/.conforma-active/context.yaml | cut -d\' \' -f2-)"'

_BARE_PYTHON3_RE = re.compile(
    r'python3\s+(scripts/|skills/)',
)

_ALREADY_PREFIXED_RE = re.compile(r'_R=.*&&\s*python3\s+"\$_R/')

_ABSOLUTE_PATH_RE = re.compile(r'python3\s+~/')


def find_all_md_files():
    """Find all .md files under skills/ that may contain python3 invocations."""
    return sorted(SKILLS_DIR.rglob("*.md"))


def rewrite_script_paths_in_file(content):
    """Rewrite bare python3 script/skills/ invocations to use $_R prefix.

    Returns (new_content, list_of_changes).
    """
    changes = []
    lines = content.split('\n')
    new_lines = []

    for line in lines:
        if _ALREADY_PREFIXED_RE.search(line):
            new_lines.append(line)
            continue
        if _ABSOLUTE_PATH_RE.search(line):
            new_lines.append(line)
            continue

        match = _BARE_PYTHON3_RE.search(line)
        if match:
            prefix = match.group(1)
            indent = line[:match.start()]
            rest_start = match.start() - len(indent)
            new_line = line[:match.start()] + _REPO_PREFIX + ' && python3 "$_R/' + line[match.start() + len('python3 '):]
            # Close the quote around the script path (before args)
            # Find the end of the path (next space or end of line, but handle quoted paths)
            path_and_args = line[match.start() + len('python3 '):]
            # Split path from args: path ends at first space not inside quotes
            parts = path_and_args.split()
            if parts:
                script_path = parts[0]
                remaining_args = ' '.join(parts[1:])
                new_line = (
                    line[:match.start()]
                    + _REPO_PREFIX + ' && python3 "$_R/' + script_path + '"'
                    + (' ' + remaining_args if remaining_args else '')
                )
                # Handle multi-line continuations: if line ends with \, keep it
                changes.append(f"  {script_path}")
            else:
                new_lines.append(line)
                continue
            new_lines.append(new_line)
        else:
            new_lines.append(line)

    return '\n'.join(new_lines), changes


def rewrite_script_paths(dry_run):
    """Rewrite all bare python3 script paths in .md files under skills/."""
    md_files = find_all_md_files()
    total_changes = 0

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        new_content, changes = rewrite_script_paths_in_file(content)

        if changes:
            rel = md_file.relative_to(REPO_ROOT)
            print(f"\n  {rel}:")
            for c in changes:
                print(f"    REWRITE: {c}")
            total_changes += len(changes)
            if not dry_run:
                md_file.write_text(new_content, encoding="utf-8")

    return total_changes


def validate_no_bare_paths():
    """Check that no bare python3 scripts/ or skills/ paths remain in code blocks."""
    md_files = find_all_md_files()
    violations = []

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        in_code_block = False
        for i, line in enumerate(content.split('\n'), 1):
            stripped = line.strip()
            if stripped.startswith('```'):
                in_code_block = not in_code_block
                continue
            if not in_code_block:
                continue
            if _ALREADY_PREFIXED_RE.search(line):
                continue
            if _ABSOLUTE_PATH_RE.search(line):
                continue
            if _BARE_PYTHON3_RE.search(line):
                rel = md_file.relative_to(REPO_ROOT)
                violations.append((rel, i, line.strip()))

    return violations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show changes without modifying files")
    parser.add_argument("--rewrite-script-paths", action="store_true",
                        help="Rewrite bare python3 script paths to use $_R prefix from context.yaml")
    parser.add_argument("--validate", action="store_true",
                        help="Check that no bare python3 script paths remain in code blocks")
    args = parser.parse_args()

    if not (REPO_ROOT / "AGENTS.md").exists():
        print("ERROR: Run from the aiops-infra repo root.", file=sys.stderr)
        sys.exit(1)

    if args.validate:
        violations = validate_no_bare_paths()
        if violations:
            print(f"FAIL: {len(violations)} bare python3 path(s) found in code blocks:")
            for rel, line_num, line in violations:
                print(f"  {rel}:{line_num}: {line}")
            sys.exit(1)
        else:
            print("OK: No bare python3 script paths in code blocks.")
            sys.exit(0)

    if args.rewrite_script_paths:
        print("Rewriting bare python3 script paths to use $_R prefix...")
        total = rewrite_script_paths(args.dry_run)
        action = "Would rewrite" if args.dry_run else "Rewrote"
        print(f"\n{action} {total} path(s).")
        sys.exit(0)

    workflow_files = find_workflow_files()
    if not workflow_files:
        print("No workflow files found under skills/conforma-*/workflows/")
        sys.exit(1)

    total_fixes = 0
    print(f"Scanning {len(workflow_files)} workflow files...\n")

    for wf in workflow_files:
        content = wf.read_text()
        original = content
        rel = wf.relative_to(REPO_ROOT)
        file_fixes = []

        content, fixes = fix_readme_links(content, wf)
        file_fixes.extend([("README link", "README.md -> ../README.md")] * len(fixes))

        content, fixes = fix_shared_reference_links(content, wf)
        file_fixes.extend([("shared ref", f"../references/{f} -> ../../references/{f}") for _, f in fixes])

        content, fixes = fix_bare_reference_links(content, wf)
        file_fixes.extend([("local ref", f"references/{f} -> ../references/{f}") for _, f in fixes])

        if content != original:
            for kind, desc in file_fixes:
                print(f"  FIX [{rel}]: {kind}: {desc}")
            if not args.dry_run:
                wf.write_text(content)
            total_fixes += len(file_fixes)

    print(f"\nFixing router SKILL.md...")
    total_fixes += fix_router_skill_md(args.dry_run)

    print(f"\n{'Would fix' if args.dry_run else 'Fixed'} {total_fixes} path(s).\n")

    if total_fixes == 0:
        print("All paths are correct — no changes needed.")
        return

    if not args.dry_run:
        print("Verifying all markdown links resolve...")
        all_files = workflow_files + [SKILLS_DIR / "conforma" / "SKILL.md"]
        errors = verify_all_links(all_files)
        if errors:
            print(f"\n  WARNING: {len(errors)} link(s) still broken:")
            for f, line, href in errors:
                print(f"    {f}:{line} -> {href}")
        else:
            print("  All markdown links resolve to existing files.")


if __name__ == "__main__":
    main()
