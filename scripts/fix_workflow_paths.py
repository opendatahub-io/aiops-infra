#!/usr/bin/env python3
"""Fix broken relative paths in conforma workflow files.

After the decomposition refactoring split SKILL.md files into
router + workflows/ subdirectories, relative paths were not adjusted
for the extra directory depth. This script fixes them.

Run from repo root:
    python3 scripts/fix_workflow_paths.py

Options:
    --dry-run    Show what would change without modifying files
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show changes without modifying files")
    args = parser.parse_args()

    if not (REPO_ROOT / "AGENTS.md").exists():
        print("ERROR: Run from the aiops-infra repo root.", file=sys.stderr)
        sys.exit(1)

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
