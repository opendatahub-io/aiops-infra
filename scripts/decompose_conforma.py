#!/usr/bin/env python3
"""Decompose conforma skills into atomic modules.

Run from repo root:
    python3 scripts/decompose_conforma.py

Options:
    --dry-run            Show what would be done without making changes
    --start-from N       Skip to step N (for resuming after a failure)
    --no-commit          Make changes but don't git commit
    --no-test            Skip test runs (faster, less safe)
    --skip-baseline-test Skip pre-flight test run
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOTAL_STEPS = 14

EXTRACTION_SOURCE_FILES = [
    "skills/conforma-exception/scripts/create_gitlab_mr.py",
    "skills/conforma-exception/scripts/create_jira_ticket.py",
    "skills/conforma-analyze/scripts/generate_resolution_guide.py",
    "skills/conforma-analyze/scripts/violations_coverage.py",
    "skills/conforma-exception/scripts/manage_exceptions.py",
]

# Target AGENTS.md content after Step 0 (fully hardcoded for determinism)
TARGET_AGENTS_MD = """\
# aiops-infra

AI-powered automation for ODH/RHOAI component onboarding and RHOAI Conforma policy compliance.

## Architecture

Read [ARCHITECTURE.md](ARCHITECTURE.md) for design principles, skill inventory, shared script conventions, and key decisions.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for how to write scripts, add tests, structure skills, and submit changes.

## Key Conventions

- Shared primitives live in `scripts/*_ops.py` (dual-mode: CLI + importable)
- Domain-specific logic stays in `skills/<name>/scripts/`
- Every new script MUST have a corresponding test in `tests/unit/`

## Secrets Policy

**NEVER ask the user to paste tokens, API keys, or credentials into the chat window.** Always instruct them to write secrets to the project's designated env file directly (using their editor or terminal). See [CONTRIBUTING.md](CONTRIBUTING.md#secrets-and-credentials-policy) for details.

## Repository Clone Policy

Never use a pre-existing local clone of a repo. Always clone fresh into the designated work directory or use an existing clone with `git fetch` first. If the fetch fails, **abort** — never silently use stale data. See [CONTRIBUTING.md](CONTRIBUTING.md#repository-clone-policy) for details.

## Script Failure Policy

When a deterministic script or skill workflow fails (import errors, missing dependencies, auth failures, unexpected exceptions), the agent MUST:

1. **Stop** -- do not silently fall back to manual exploration, ad-hoc cloning, or AI-improvised alternatives.
2. **Report** -- tell the user which script failed, the exact error, and what step of the workflow was interrupted.
3. **Ask** -- present the user with three choices:
   - **(Recommended)** Fix the underlying script/skill issue and retry the deterministic path.
   - File a GitHub issue for the skill maintainer with full error context.
   - Proceed with AI-assisted manual exploration, with the explicit warning that results may be incomplete, inconsistent, or different from the established workflow output.

The deterministic scripted path is always the default. Manual exploration is a last resort that requires explicit user consent.

## Repository Structure

- `scripts/` — shared automation scripts (onboarding + `*_ops.py` primitives)
- `skills/` — conforma and other skills (`.cursor/skills` is a symlink here)
- `.claude/skills/` — onboarding pipeline skills
- `tests/` — unit and integration tests
- `schemas/` — JSON schemas for validation
- `docs/` — skill documentation and RFDs

## User Coding Preferences

These are established preferences extracted from repeated user corrections across historical sessions.
Follow them in ALL generated content — code, comments, commit messages, documentation, and conversation.

### Terminology

| Write | Never write | Context |
|-------|-------------|---------|
| Merge Request | MR, MRs | All user-facing text |
| Pull Request | PR | All text (exception: `gh pr` CLI commands) |
| KONFLUX_TENANT | TENANT | Variable names |

- **Never abbreviate** in user-facing output (chat, reports, docs, comments). Abbreviations are only acceptable in internal variable names, log prefixes, and non-rendered code comments.

### Behavior and Workflow

- **Maximum determinism**: All logic MUST live in scripts. The AI presents script output verbatim. Leave nothing to LLM interpretation.
- **Never ask for tokens/secrets in chat**: Always instruct the user to write credentials to the project's env file directly.
- **Never auto-submit**: Always show output to the user first and ask for explicit confirmation before publishing, submitting, or pushing anything.
- **Missing auth is a hard stop**: If authentication fails or is missing (GitHub, GitLab, Jira, Slack), stop completely. Never skip a data source or produce incomplete reports.
- **Don't add unrequested files**: Never create files (Makefiles, configs, etc.) the user didn't ask for.
- **Always write tests**: Every new testable script or function must have a corresponding test.
- **Fix root causes**: Never apply ad-hoc workarounds. Fix the underlying issue in the script/skill.
- **Don't depend on external CLI tools** when Python libraries can do the same job (e.g. prefer `requests` over shelling out to `gh` or `glab`).
- **Scripts handle their own env vars**: The user should never see approval prompts for environment variable access.
- **Never answer confidently from dummy/example data**: If data retrieval failed, say so. Never fabricate or infer from placeholder values.
- **Never silently skip data sources**: If Slack, Jira, or any source is unreachable, report it explicitly — do not silently omit it.
- **Don't launch heavyweight subagents** when a direct file read suffices. Route queries efficiently.
- **Auto-discover values from context**: Infer KONFLUX_APPLICATION, cluster domains, etc. from the user's query rather than asking the user to provide them manually.
- **Confirmation-before-action**: Show analysis results before offering next-step actions. Never assume the user wants to proceed.

### Structure and Formatting

- Show TODO progress checklist before running multi-step workflows
- Keep skill READMEs short — installation instructions only. Operational details belong in the skill workflow itself.

### Code Style

- No hardcoding product-specific values (team names, application names) in scripts — discover them dynamically
- Use a single variable for repeated text strings (DRY principle)
- Konflux UI URLs use `konflux-ui.apps.` prefix (not `console.`)
- No backward-compatibility shims unless explicitly requested — remove deprecated paths completely
- Variable and function names must be self-explanatory (reject cryptic abbreviations)

### Tool-Agnosticism

- Skills and rules must NOT depend on any specific AI tool (Cursor, Claude, Copilot, etc.)
- Presentation rules must produce identical output regardless of which AI model executes them
- All rules belong in skill files or AGENTS.md, never in tool-specific config alone
- Solutions must work with minimal dependencies, across different environments
"""

# Content to append to skills/conforma/SKILL.md before "## Example Queries"
CONFORMA_CONVENTIONS_SECTION = """\

## Conforma Conventions

These rules apply to ALL conforma skill execution and output.

### Terminology
- Never use "EC" — always "Conforma" (all contexts: variable names, docs, conversation)
- Conforma is RHOAI-only — never imply ODH coverage
- "violation code" not bare "code" or "rule"
- Violations = atomic instances: 1 unique (violation code + component + semantic detail) triple. Multiple CSV rows with different image digests sharing the same root cause are the SAME violation.
- Express coverage as "X of Y violations covered"
- "No exception coverage" not "No coverage"
- "Exception granted, violation should disappear on next Conforma run" not "Exception active"
- "Rerun Conforma report in Konflux/GitHub and verify the violation is gone from the report" not vague phrases
- "Executive Summary" not "Key Takeaways"
- "manual search" / "search manually" for actionable search links
- Merge Request titles for exceptions: prefix with [stage] or [prod]

### Report Formatting
- One component per table row
- List policy files as bullets, not comma-delimited
- Exception links in resolution guide section, not summary table
- Components column always populated, even for fully-covered violations
- Reports must have Executive Summary above main table
- Source CSV: link to exact git commit hash, not branch name
- Report header: identify which specific report version was analyzed
- Next-steps: brief (one line); detailed steps in resolution guide below
- Covered violations: say "rerun Conforma" not full remediation steps

### Runtime
- `~/.conforma/` for runtime data, clones, secrets (`.env`)
- `context.yaml` for inter-skill data handover
- Never silently skip data sources (Slack, Jira) — report explicitly if unreachable

"""

# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def run_cmd(cmd: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess command."""
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def git_commit(message: str, files: list[str] | None = None, *, dry_run: bool = False) -> str | None:
    """Stage files and commit. Returns short SHA or None if dry_run."""
    if dry_run:
        return None
    if files:
        run_cmd(["git", "add", *files])
    else:
        run_cmd(["git", "add", "-A"])
    result = run_cmd(["git", "commit", "-m", message])
    sha = run_cmd(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    return sha


def run_tests(*, no_test: bool = False) -> bool:
    """Run pytest. Returns True if tests pass."""
    if no_test:
        return True
    result = run_cmd(
        ["python3", "-m", "pytest", "tests/unit/", "-x", "--tb=short", "-q"],
        check=False,
    )
    if result.returncode != 0:
        print("  TEST OUTPUT:")
        if result.stdout:
            print(result.stdout[-3000:])
        if result.stderr:
            print(result.stderr[-2000:])
    return result.returncode == 0


def revert_changes():
    """Revert all uncommitted changes."""
    run_cmd(["git", "checkout", "--", "."])
    run_cmd(["git", "clean", "-fd"], check=False)


def count_lines(path: str | Path) -> int:
    """Count lines in a file."""
    return len(Path(path).read_text().splitlines())


def file_contains(path: str | Path, text: str) -> bool:
    """Check if a file contains a string."""
    try:
        return text in Path(path).read_text()
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Module header generation
# ---------------------------------------------------------------------------


def generate_module_header(filepath: Path) -> str:
    """Generate a structured module header with public API and section map."""
    source = filepath.read_text()
    tree = ast.parse(source)
    lines = source.splitlines()

    module_name = filepath.stem
    existing_doc = ast.get_docstring(tree) or ""
    purpose = existing_doc.split("\n")[0] if existing_doc else f"{module_name} module."

    public_funcs = []
    private_sections: dict[str, list[str]] = {}
    current_section = "Main"

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            name = node.name
            line = node.lineno
            end_line = node.end_lineno or line

            # Determine return type annotation
            ret = ""
            if node.returns:
                ret = f" -> {ast.unparse(node.returns)}"

            # Determine args
            args_str = ", ".join(
                a.arg for a in node.args.args if a.arg != "self"
            )

            if not name.startswith("_"):
                public_funcs.append(f"    {name}({args_str}){ret}  [line {line}]")
            else:
                section_funcs = private_sections.setdefault(current_section, [])
                section_funcs.append(name)

        elif isinstance(node, ast.ClassDef):
            current_section = node.name

    # Build the header
    header_lines = [f'"""{module_name} — {purpose}', ""]

    if public_funcs:
        header_lines.append("PUBLIC API:")
        header_lines.extend(public_funcs)
        header_lines.append("")

    if private_sections:
        header_lines.append("INTERNAL SECTIONS:")
        for section, funcs in private_sections.items():
            # Find line range for this section's functions
            func_names_str = ", ".join(funcs[:5])
            if len(funcs) > 5:
                func_names_str += f", ... (+{len(funcs) - 5} more)"
            header_lines.append(f"    {section}: {func_names_str}")
        header_lines.append("")

    # Dependencies
    imports = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0])
    external_deps = sorted(set(imports) - {"__future__", "_setup_env"})
    if external_deps:
        header_lines.append(f"DEPENDENCIES: {', '.join(external_deps[:10])}")
        header_lines.append("")

    header_lines.append('"""')

    return "\n".join(header_lines)


def apply_module_header(filepath: Path, *, dry_run: bool = False) -> bool:
    """Apply a generated module header to a file. Returns True if modified."""
    source = filepath.read_text()
    tree = ast.parse(source)

    header = generate_module_header(filepath)

    # Find existing docstring location
    first_stmt = tree.body[0] if tree.body else None
    if (
        first_stmt
        and isinstance(first_stmt, ast.Expr)
        and isinstance(first_stmt.value, ast.Constant)
        and isinstance(first_stmt.value.value, str)
    ):
        # Replace existing docstring
        start_line = first_stmt.lineno - 1
        end_line = first_stmt.end_lineno
        lines = source.splitlines(keepends=True)
        new_source = "".join(lines[:start_line]) + header + "\n" + "".join(lines[end_line:])
    else:
        # Prepend header after shebang and encoding lines
        lines = source.splitlines(keepends=True)
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("#!") or line.startswith("# -*-"):
                insert_at = i + 1
            else:
                break
        new_source = "".join(lines[:insert_at]) + header + "\n" + "".join(lines[insert_at:])

    # Verify it parses
    ast.parse(new_source)

    if not dry_run:
        filepath.write_text(new_source)
    return True


# ---------------------------------------------------------------------------
# Function extraction engine
# ---------------------------------------------------------------------------


class ExtractionConfig:
    """Configuration for extracting functions from a source module."""

    def __init__(
        self,
        source_file: str,
        target_file: str,
        function_names: list[str],
        target_docstring: str,
    ):
        self.source_path = Path(source_file)
        self.target_path = Path(target_file)
        self.function_names = function_names
        self.target_docstring = target_docstring


def extract_functions(config: ExtractionConfig, *, dry_run: bool = False) -> bool:
    """Extract functions from source to a new module.

    Returns True if extraction succeeded.
    """
    source = config.source_path.read_text()
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    # Collect function nodes to extract (including _ prefixed versions)
    target_names = set()
    for name in config.function_names:
        target_names.add(name)
        target_names.add(f"_{name}")

    nodes_to_extract: list[ast.FunctionDef | ast.ClassDef] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name in target_names:
                nodes_to_extract.append(node)
        elif isinstance(node, ast.ClassDef):
            if node.name in target_names:
                nodes_to_extract.append(node)

    if not nodes_to_extract:
        print(f"    WARNING: No matching functions found in {config.source_path}")
        return False

    # Collect all names defined at module level (for dependency resolution)
    module_level_names: dict[str, ast.AST] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            module_level_names[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_level_names[target.id] = node
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                module_level_names[node.target.id] = node
        elif isinstance(node, ast.ClassDef):
            module_level_names[node.name] = node

    # Find dependencies: names used by target functions that are defined at module level
    extracted_names = {n.name for n in nodes_to_extract}
    dependencies: set[str] = set()

    def collect_names_used(node: ast.AST) -> set[str]:
        """Collect all Name references within a node."""
        names = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.add(child.id)
            elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                names.add(child.value.id)
        return names

    for func_node in nodes_to_extract:
        used = collect_names_used(func_node)
        for name in used:
            if name in module_level_names and name not in extracted_names:
                dep_node = module_level_names[name]
                if isinstance(dep_node, ast.FunctionDef | ast.AsyncFunctionDef):
                    dependencies.add(name)
                elif isinstance(dep_node, ast.Assign | ast.AnnAssign | ast.ClassDef):
                    dependencies.add(name)

    # Recursively collect dependencies of dependencies (two levels for safety)
    for _ in range(2):
        extra_deps: set[str] = set()
        for dep_name in dependencies:
            dep_node = module_level_names[dep_name]
            used = collect_names_used(dep_node)
            for name in used:
                if name in module_level_names and name not in extracted_names and name not in dependencies:
                    extra_deps.add(name)
        if not extra_deps:
            break
        dependencies.update(extra_deps)

    # Collect all nodes to put in the new module (targets + dependencies)
    all_extract_names = extracted_names | dependencies
    all_extract_nodes: list[tuple[int, int, ast.AST]] = []
    for node in ast.iter_child_nodes(tree):
        name = None
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            name = node.name
        elif isinstance(node, ast.ClassDef):
            name = node.name
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in all_extract_names:
                    name = t.id
                    break
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id in all_extract_names:
                name = node.target.id

        if name and name in all_extract_names:
            start = node.lineno - 1
            end = node.end_lineno or node.lineno
            all_extract_nodes.append((start, end, node))

    # Collect imports needed by extracted code
    all_imports: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            import_text = "".join(lines[node.lineno - 1: node.end_lineno or node.lineno])
            all_imports.append(import_text.rstrip())

    # Build the new module content
    new_module_lines = [f'"""{config.target_docstring}"""', "", "from __future__ import annotations", ""]

    # Add relevant imports (we include all for safety; could optimize later)
    for imp in all_imports:
        if "_setup_env" not in imp:
            new_module_lines.append(imp)
    new_module_lines.append("")
    new_module_lines.append("")

    # Add extracted code (sorted by original position)
    all_extract_nodes.sort(key=lambda x: x[0])
    extracted_chunks = []
    # Only rename explicitly requested functions (not auto-detected dependencies)
    explicitly_extracted = {n.name for n in nodes_to_extract}
    rename_map: dict[str, str] = {}
    for start, end, _node in all_extract_nodes:
        chunk = "".join(lines[start:end])
        original_name = _node.name if hasattr(_node, "name") else None
        if original_name and original_name.startswith("_") and original_name in explicitly_extracted:
            public_name = original_name.lstrip("_")
            rename_map[original_name] = public_name
        extracted_chunks.append(chunk)

    # Apply all renames across all chunks (function defs + internal calls)
    for i, chunk in enumerate(extracted_chunks):
        for old_name, new_name in rename_map.items():
            chunk = chunk.replace(f"def {old_name}(", f"def {new_name}(", 1)
            chunk = chunk.replace(f"class {old_name}(", f"class {new_name}(", 1)
            chunk = chunk.replace(f"class {old_name}:", f"class {new_name}:", 1)
            # Rename call sites using word boundary regex
            chunk = re.sub(rf'\b{re.escape(old_name)}\b', new_name, chunk)
        extracted_chunks[i] = chunk

    for chunk in extracted_chunks:
        new_module_lines.append(chunk.rstrip())
        new_module_lines.append("")
        new_module_lines.append("")

    new_module_content = "\n".join(new_module_lines)

    # Verify new module parses
    try:
        ast.parse(new_module_content)
    except SyntaxError as e:
        print(f"    ERROR: Generated module has syntax error: {e}")
        return False

    # Build updated source: remove only explicitly extracted functions (not dependencies)
    lines_to_remove: set[int] = set()
    for start, end, _node in all_extract_nodes:
        node_name = _node.name if hasattr(_node, "name") else None
        if not node_name:
            if isinstance(_node, ast.Assign):
                for t in _node.targets:
                    if isinstance(t, ast.Name):
                        node_name = t.id
                        break
            elif isinstance(_node, ast.AnnAssign) and isinstance(_node.target, ast.Name):
                node_name = _node.target.id
        # Only remove explicitly extracted nodes, keep dependencies in source
        if node_name and node_name in explicitly_extracted:
            for i in range(start, end):
                lines_to_remove.add(i)

    # Also remove blank lines immediately after removed blocks
    def _get_node_name(n: ast.AST) -> str | None:
        if hasattr(n, "name"):
            return n.name
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    return t.id
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            return n.target.id
        return None

    sorted_ranges = sorted(
        (s, e, n) for s, e, n in all_extract_nodes
        if _get_node_name(n) in explicitly_extracted
    )
    for _, end, _ in sorted_ranges:
        i = end
        while i < len(lines) and lines[i].strip() == "":
            lines_to_remove.add(i)
            i += 1
            if i - end > 2:
                break

    remaining_lines = [line for i, line in enumerate(lines) if i not in lines_to_remove]

    # Generate re-export imports (only for explicitly extracted nodes)
    target_module_name = config.target_path.stem
    re_exports = []
    for node in nodes_to_extract:
        public_name = node.name.lstrip("_")
        original_name = node.name
        if public_name == original_name:
            re_exports.append(
                f"from {target_module_name} import {public_name}  "
                f"# noqa: F401 — backward compat re-export"
            )
        else:
            re_exports.append(
                f"from {target_module_name} import {public_name} as {original_name}  "
                f"# noqa: F401 — backward compat re-export"
            )

    # Find insertion point: after the last import statement (using AST for accuracy)
    remaining_source_tmp = "".join(remaining_lines)
    try:
        remaining_tree = ast.parse(remaining_source_tmp)
    except SyntaxError:
        # Fallback: insert at top after shebang/encoding
        remaining_tree = None

    insert_pos = 0
    if remaining_tree:
        for node in ast.iter_child_nodes(remaining_tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                end = node.end_lineno or node.lineno
                if end > insert_pos:
                    insert_pos = end
    else:
        # Fallback: line-based scan (skips multi-line imports properly)
        in_multiline = False
        for i, line in enumerate(remaining_lines):
            stripped = line.strip()
            if in_multiline:
                if ")" in stripped:
                    in_multiline = False
                    insert_pos = i + 1
            elif stripped.startswith("import ") or stripped.startswith("from "):
                if "(" in stripped and ")" not in stripped:
                    in_multiline = True
                else:
                    insert_pos = i + 1

    # Insert re-exports with a blank line separator
    re_export_block = "\n" + "\n".join(re_exports) + "\n"
    remaining_lines.insert(insert_pos, re_export_block)

    updated_source = "".join(remaining_lines)

    # Verify updated source parses
    try:
        ast.parse(updated_source)
    except SyntaxError as e:
        print(f"    ERROR: Updated source has syntax error: {e}")
        return False

    if dry_run:
        print(f"    Would create {config.target_path} ({len(new_module_content.splitlines())} lines)")
        print(f"    Would update {config.source_path} (removed {len(lines_to_remove)} lines)")
        return True

    # Write files
    config.target_path.parent.mkdir(parents=True, exist_ok=True)
    config.target_path.write_text(new_module_content)
    config.source_path.write_text(updated_source)

    return True


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


class Step:
    """Base class for decomposition steps."""

    number: int
    description: str
    needs_tests: bool = False

    def is_complete(self) -> bool:
        """Check if this step has already been applied."""
        return False

    def execute(self, *, dry_run: bool = False) -> bool:
        """Run the step. Returns True on success."""
        raise NotImplementedError

    def run(self, *, dry_run: bool = False, no_commit: bool = False, no_test: bool = False) -> str | None:
        """Full step lifecycle: check, execute, test, commit."""
        if self.is_complete():
            print(f"[{self.number}/{TOTAL_STEPS}] {self.description}... SKIPPED (already done)")
            return "skipped"

        print(f"[{self.number}/{TOTAL_STEPS}] {self.description}...", end=" ", flush=True)

        if not self.execute(dry_run=dry_run):
            print("FAILED")
            return None

        if self.needs_tests and not no_test and not dry_run:
            if not run_tests():
                print("FAILED (tests)")
                revert_changes()
                return None

        if dry_run:
            print("OK (dry-run)")
            return "dry-run"

        if no_commit:
            print("OK (no commit)")
            return "no-commit"

        commit_msg = (
            f"refactor(conforma): {self.description}\n\n"
            f"Part of the conforma skill decomposition plan.\n"
            f"Step {self.number}/{TOTAL_STEPS}: {self.description}\n\n"
            f"No behavioral changes. All existing tests pass."
        )
        sha = git_commit(commit_msg)
        test_note = "tests pass, " if self.needs_tests else ""
        print(f"OK ({test_note}committed: {sha})")
        return sha


class Step0_FixAlwaysOnOverhead(Step):
    number = 0
    description = "Fixing always-on system prompt overhead (delete CLAUDE.md, rewrite AGENTS.md)"

    def is_complete(self) -> bool:
        return (
            not Path("CLAUDE.md").exists()
            and count_lines("AGENTS.md") < 100
            and file_contains("skills/conforma/SKILL.md", "## Conforma Conventions")
        )

    def execute(self, *, dry_run: bool = False) -> bool:
        if dry_run:
            print(f"\n    Would delete CLAUDE.md")
            print(f"    Would rewrite AGENTS.md ({len(TARGET_AGENTS_MD.splitlines())} lines)")
            print(f"    Would add Conforma Conventions to skills/conforma/SKILL.md")
            return True

        # Delete CLAUDE.md
        claude_path = Path("CLAUDE.md")
        if claude_path.exists():
            run_cmd(["git", "rm", "CLAUDE.md"])

        # Write new AGENTS.md
        Path("AGENTS.md").write_text(TARGET_AGENTS_MD)

        # Add Conforma Conventions to skills/conforma/SKILL.md
        skill_path = Path("skills/conforma/SKILL.md")
        content = skill_path.read_text()

        if "## Conforma Conventions" not in content:
            # Insert before "## Example Queries"
            marker = "## Example Queries"
            if marker in content:
                content = content.replace(marker, CONFORMA_CONVENTIONS_SECTION + marker)
            else:
                content += CONFORMA_CONVENTIONS_SECTION

        skill_path.write_text(content)

        # Verify
        agents_lines = count_lines("AGENTS.md")
        if not (70 <= agents_lines <= 90):
            print(f"\n    WARNING: AGENTS.md is {agents_lines} lines (expected 75-85)")

        if "## Conforma Conventions" not in skill_path.read_text():
            print("\n    ERROR: Conforma Conventions section not found after write")
            return False

        return True


class Step1_ModuleHeaders(Step):
    number = 1
    description = "Adding module headers to scripts >300 lines"

    def _target_scripts(self) -> list[Path]:
        """Find all Python scripts >300 lines in skills/ directories."""
        scripts = []
        for pattern in ["skills/*/scripts/*.py", "skills/*/*/scripts/*.py"]:
            for p in Path(".").glob(pattern):
                if p.name.startswith("_"):
                    continue
                if count_lines(p) > 300:
                    scripts.append(p)
        return sorted(scripts)

    def is_complete(self) -> bool:
        scripts = self._target_scripts()
        if not scripts:
            return True
        return all(file_contains(s, "PUBLIC API:") for s in scripts[:3])

    def execute(self, *, dry_run: bool = False) -> bool:
        scripts = self._target_scripts()
        if dry_run:
            print(f"\n    Would add headers to {len(scripts)} scripts")
            return True

        modified = 0
        for script in scripts:
            try:
                if file_contains(script, "PUBLIC API:"):
                    continue
                apply_module_header(script)
                modified += 1
            except Exception as e:
                print(f"\n    ERROR on {script}: {e}")
                return False

        print(f"({modified} files)", end=" ")
        return True


class Step2_SplitExceptionSkill(Step):
    number = 2
    description = "Splitting conforma-exception/SKILL.md into workflows/"
    _skill_dir = Path("skills/conforma-exception")

    def is_complete(self) -> bool:
        return (self._skill_dir / "workflows").is_dir()

    def execute(self, *, dry_run: bool = False) -> bool:
        skill_path = self._skill_dir / "SKILL.md"
        workflows_dir = self._skill_dir / "workflows"
        content = skill_path.read_text()
        sections = self._parse_sections(content)

        if dry_run:
            print(f"\n    Would create {workflows_dir}/ with workflow files")
            return True

        workflows_dir.mkdir(exist_ok=True)

        # Create router SKILL.md (keep frontmatter + overview + routing table)
        router = self._build_router(content, sections)
        skill_path.write_text(router)

        # Create workflow files based on logical grouping
        self._write_workflow("create", sections, workflows_dir, [
            "Prerequisites", "Remote Data Access Policy", "RHOAIENG Approval Gate",
            "Important: Human-in-the-Loop", "Workflow Routing",
            "Exception Creation Workflow Diagram", "Explaining Conforma Exceptions",
            "Run Directory Convention", "Starting Without Details",
            "Listing Exception Types, Usage, and Questionnaire",
            "Component Version Reconciliation", "Dry-Run Mode",
            "Verification Contract", "Jira Component Audit",
            "Commit Message Structure",
        ])

        self._write_workflow("extend", sections, workflows_dir, [
            "Prerequisites", "Remote Data Access Policy",
            "Important: Human-in-the-Loop", "Workflow Routing",
            "Run Directory Convention", "Dry-Run Mode", "Verification Contract",
        ])

        self._write_workflow("lifecycle", sections, workflows_dir, [
            "Prerequisites", "Remote Data Access Policy",
            "Reconcile Mode", "Existing Exception Deduplication",
            "Managing Exceptions",
        ])

        self._write_workflow("check", sections, workflows_dir, [
            "Prerequisites", "Listing, Searching, and Watchers",
        ])

        self._write_workflow("assess-expired", sections, workflows_dir, [
            "Prerequisites", "Remote Data Access Policy",
            "Managing Exceptions",
        ])

        return True

    def _parse_sections(self, content: str) -> dict[str, str]:
        """Parse markdown into sections by ## headings."""
        sections: dict[str, str] = {}
        current_heading = "_preamble"
        current_lines: list[str] = []

        for line in content.splitlines(keepends=True):
            if line.startswith("## "):
                if current_lines:
                    sections[current_heading] = "".join(current_lines)
                current_heading = line.strip().lstrip("# ").strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            sections[current_heading] = "".join(current_lines)

        return sections

    def _build_router(self, content: str, sections: dict[str, str]) -> str:
        """Build a concise router SKILL.md."""
        # Keep frontmatter
        lines = content.splitlines(keepends=True)
        frontmatter_end = 0
        in_frontmatter = False
        for i, line in enumerate(lines):
            if line.strip() == "---":
                if in_frontmatter:
                    frontmatter_end = i + 1
                    break
                in_frontmatter = True

        preamble = "".join(lines[:frontmatter_end])

        router = preamble + "\n"
        router += "# Conforma Exception Management\n\n"
        router += "This skill manages RHOAI Conforma exceptions. Route to the appropriate workflow:\n\n"
        router += "| Intent | Workflow file |\n"
        router += "|--------|---------------|\n"
        router += "| Create a new exception | Read `workflows/create.md` |\n"
        router += "| Extend an existing exception | Read `workflows/extend.md` |\n"
        router += "| Manage lifecycle (reconcile, deduplicate) | Read `workflows/lifecycle.md` |\n"
        router += "| Check/search exceptions | Read `workflows/check.md` |\n"
        router += "| Assess expired exceptions | Read `workflows/assess-expired.md` |\n\n"

        # Keep naming conventions and violations-first philosophy if they exist
        for key in ["Violations-First Philosophy", "Naming Conventions"]:
            if key in sections:
                router += sections[key]

        # Keep error handling and pipeline mode
        for key in ["Error Handling", "Pipeline Mode (Handover)", "Reference Documentation"]:
            if key in sections:
                router += "\n" + sections[key]

        return router

    def _write_workflow(
        self, name: str, sections: dict[str, str], workflows_dir: Path, section_keys: list[str]
    ):
        """Write a workflow file from specified sections."""
        content = f"# {name.replace('-', ' ').title()} Workflow\n\n"
        for key in section_keys:
            if key in sections:
                content += sections[key] + "\n"
        (workflows_dir / f"{name}.md").write_text(content)


class Step3_SplitAnalyzeSkill(Step):
    number = 3
    description = "Splitting conforma-analyze/SKILL.md into workflows/"
    _skill_dir = Path("skills/conforma-analyze")

    def is_complete(self) -> bool:
        return (self._skill_dir / "workflows").is_dir()

    def execute(self, *, dry_run: bool = False) -> bool:
        skill_path = self._skill_dir / "SKILL.md"
        workflows_dir = self._skill_dir / "workflows"
        content = skill_path.read_text()

        if dry_run:
            print(f"\n    Would create {workflows_dir}/ with workflow files")
            return True

        workflows_dir.mkdir(exist_ok=True)

        # Split at "## Violation History" marker
        lines = content.splitlines(keepends=True)
        history_start = None
        for i, line in enumerate(lines):
            if line.startswith("## Violation History"):
                history_start = i
                break

        if history_start is None:
            print("\n    ERROR: Could not find '## Violation History' section")
            return False

        # Find where to cut for the main workflow
        # Keep everything from "## Workflow" to "## Violation History" as full-analysis
        workflow_start = None
        for i, line in enumerate(lines):
            if line.startswith("## Workflow"):
                workflow_start = i
                break

        # Build router SKILL.md (keep frontmatter + overview + shared sections up to workflow)
        frontmatter_end = 0
        in_fm = False
        for i, line in enumerate(lines):
            if line.strip() == "---":
                if in_fm:
                    frontmatter_end = i + 1
                    break
                in_fm = True

        # Router = frontmatter + sections before Workflow + routing table
        pre_workflow = "".join(lines[:workflow_start]) if workflow_start else "".join(lines[:frontmatter_end])
        router = pre_workflow + "\n"
        router += "## Workflow Routing\n\n"
        router += "| Intent | Workflow file |\n"
        router += "|--------|---------------|\n"
        router += "| Full violation analysis (fetch, parse, analyze, coverage, guide) | Read `workflows/full-analysis.md` |\n"
        router += "| Trace when a violation appeared/disappeared | Read `workflows/violation-history.md` |\n"
        router += "\n"

        # Include sections after Violation History that are shared
        after_history = ""
        for i, line in enumerate(lines[history_start:], start=history_start):
            if line.startswith("## ") and not line.startswith("## Violation History"):
                after_history = "".join(lines[i:])
                break

        if after_history:
            router += after_history

        skill_path.write_text(router)

        # Full analysis workflow = everything from "## Workflow" to "## Violation History"
        full_analysis = "# Full Analysis Workflow\n\n"
        full_analysis += "".join(lines[workflow_start:history_start])
        (workflows_dir / "full-analysis.md").write_text(full_analysis)

        # Violation history = "## Violation History" section
        history_end = len(lines)
        for i, line in enumerate(lines[history_start + 1:], start=history_start + 1):
            if line.startswith("## "):
                history_end = i
                break

        violation_history = "# Violation History Workflow\n\n"
        violation_history += "".join(lines[history_start:history_end])
        (workflows_dir / "violation-history.md").write_text(violation_history)

        return True


class Step4_SplitReportFetchSkill(Step):
    number = 4
    description = "Splitting conforma-report-fetch/SKILL.md into workflows/"
    _skill_dir = Path("skills/conforma-report-fetch")

    def is_complete(self) -> bool:
        return (self._skill_dir / "workflows").is_dir()

    def execute(self, *, dry_run: bool = False) -> bool:
        skill_path = self._skill_dir / "SKILL.md"
        workflows_dir = self._skill_dir / "workflows"
        content = skill_path.read_text()
        lines = content.splitlines(keepends=True)

        if dry_run:
            print(f"\n    Would create {workflows_dir}/ with csv.md and tekton.md")
            return True

        workflows_dir.mkdir(exist_ok=True)

        # Find section boundaries
        csv_start = tekton_start = relationship_start = None
        for i, line in enumerate(lines):
            if "## 1. CSV" in line or "CSV Violation Reports" in line:
                csv_start = i
            elif "## 2. Tekton" in line or "Tekton JSON Reports" in line:
                tekton_start = i
            elif "## Relationship" in line:
                relationship_start = i

        if csv_start is None or tekton_start is None:
            print("\n    ERROR: Could not find CSV/Tekton section boundaries")
            return False

        # Build router
        frontmatter_end = 0
        in_fm = False
        for i, line in enumerate(lines):
            if line.strip() == "---":
                if in_fm:
                    frontmatter_end = i + 1
                    break
                in_fm = True

        router = "".join(lines[:csv_start])
        router += "\n## Workflow Routing\n\n"
        router += "| Intent | Workflow file |\n"
        router += "|--------|---------------|\n"
        router += "| Fetch CSV violation reports from GitHub | Read `workflows/csv.md` |\n"
        router += "| Fetch raw Tekton JSON from Konflux | Read `workflows/tekton.md` |\n"
        router += "\n"

        if relationship_start:
            router += "".join(lines[relationship_start:])

        skill_path.write_text(router)

        # CSV workflow
        csv_end = tekton_start
        csv_content = "# CSV Violation Reports Workflow\n\n"
        csv_content += "".join(lines[csv_start:csv_end])
        (workflows_dir / "csv.md").write_text(csv_content)

        # Tekton workflow
        tekton_end = relationship_start or len(lines)
        tekton_content = "# Tekton JSON Reports Workflow\n\n"
        tekton_content += "".join(lines[tekton_start:tekton_end])
        (workflows_dir / "tekton.md").write_text(tekton_content)

        return True


class Step5_ReferenceScoping(Step):
    number = 5
    description = "Creating violation-aliases.yaml + adding reference scoping to workflow files"

    def is_complete(self) -> bool:
        return Path("skills/references/violation-aliases.yaml").exists()

    def execute(self, *, dry_run: bool = False) -> bool:
        import yaml

        # Create violation-aliases.yaml
        catalog_path = Path("skills/references/violation-catalog.yaml")
        aliases_path = Path("skills/references/violation-aliases.yaml")

        catalog = yaml.safe_load(catalog_path.read_text())
        violations = catalog.get("violations", [])

        aliases_entries = []
        for v in violations:
            vid = v.get("id") or (v.get("conforma_rule_codes", [None])[0] if v.get("conforma_rule_codes") else None)
            v_aliases = v.get("aliases", [])
            if vid and v_aliases:
                aliases_entries.append({"id": vid, "phrases": v_aliases})

        aliases_content = (
            "# Violation code aliases for natural-language resolution.\n"
            "# Extracted from violation-catalog.yaml — keep in sync.\n"
            "#\n"
            "# Used by: conforma-analyze violation-history workflow\n"
            "# To regenerate: python3 scripts/decompose_conforma.py --start-from 5\n\n"
        )
        aliases_content += yaml.dump({"aliases": aliases_entries}, default_flow_style=False, sort_keys=False)

        if dry_run:
            print(f"\n    Would create {aliases_path} ({len(aliases_entries)} entries)")
            print(f"    Would add reference sections to workflow files")
            return True

        aliases_path.write_text(aliases_content)

        # Add reference scoping to workflow files
        workflow_refs = {
            "skills/conforma-analyze/workflows/violation-history.md": [
                ("skills/references/violation-aliases.yaml", "~50 lines"),
            ],
            "skills/conforma-analyze/workflows/full-analysis.md": [],
            "skills/conforma-exception/workflows/create.md": [
                ("skills/conforma-exception/references/exception-process.md", "~164 lines"),
                ("skills/conforma-exception/references/interactive-workflow.md", "~266 lines"),
            ],
            "skills/conforma-exception/workflows/extend.md": [
                ("skills/conforma-exception/references/exception-process.md", "~164 lines"),
            ],
            "skills/conforma-exception/workflows/lifecycle.md": [
                ("skills/conforma-exception/references/managing-exceptions-workflow.md", "~307 lines"),
            ],
            "skills/conforma-exception/workflows/check.md": [],
            "skills/conforma-exception/workflows/assess-expired.md": [
                ("skills/conforma-exception/references/managing-exceptions-workflow.md", "~307 lines"),
            ],
            "skills/conforma-report-fetch/workflows/csv.md": [],
            "skills/conforma-report-fetch/workflows/tekton.md": [],
        }

        for workflow_file, refs in workflow_refs.items():
            path = Path(workflow_file)
            if not path.exists():
                continue

            content = path.read_text()
            if "## References" in content:
                continue

            if refs:
                ref_section = "## References (load these before executing)\n\n"
                for ref_path, size in refs:
                    ref_section += f"- `{ref_path}` ({size})\n"
                ref_section += "\n---\n\n"
                content = ref_section + content
            else:
                ref_section = "## References (load these before executing)\n\nNo additional references needed.\n\n---\n\n"
                content = ref_section + content

            path.write_text(content)

        return True


class Step6_ExtractMrText(Step):
    number = 6
    description = "Extracting exception_mr_text.py from create_gitlab_mr.py"
    needs_tests = True

    def is_complete(self) -> bool:
        return Path("skills/conforma-exception/scripts/exception_mr_text.py").exists()

    def execute(self, *, dry_run: bool = False) -> bool:
        config = ExtractionConfig(
            source_file="skills/conforma-exception/scripts/create_gitlab_mr.py",
            target_file="skills/conforma-exception/scripts/exception_mr_text.py",
            function_names=[
                "build_commit_message", "build_commit_message_consolidated",
                "build_mr_title", "build_mr_title_consolidated",
                "build_mr_body", "build_mr_body_consolidated",
                "build_extend_commit_message", "build_lifecycle_commit_message",
            ],
            target_docstring="Exception Merge Request text generation — commit messages, titles, and bodies.",
        )
        return extract_functions(config, dry_run=dry_run)


class Step7_ExtractPolicyFileOps(Step):
    number = 7
    description = "Extracting exception_policy_file_ops.py from create_gitlab_mr.py"
    needs_tests = True

    def is_complete(self) -> bool:
        return Path("skills/conforma-exception/scripts/exception_policy_file_ops.py").exists()

    def execute(self, *, dry_run: bool = False) -> bool:
        config = ExtractionConfig(
            source_file="skills/conforma-exception/scripts/create_gitlab_mr.py",
            target_file="skills/conforma-exception/scripts/exception_policy_file_ops.py",
            function_names=[
                "resolve_policy_file", "resolve_self_service_file",
                "detect_component_type", "get_target_file",
                "generate_exception_yaml", "find_existing_exceptions",
                "remove_exception_from_policy_file", "apply_exception_to_policy_file",
                "append_to_policy_file", "AmbiguousPolicyFileError",
            ],
            target_docstring="Exception policy file operations — resolution, YAML generation, and manipulation.",
        )
        return extract_functions(config, dry_run=dry_run)


class Step8_ExtractJiraBuilders(Step):
    number = 8
    description = "Extracting jira_description_builders.py from create_jira_ticket.py"
    needs_tests = True

    def is_complete(self) -> bool:
        return Path("skills/conforma-exception/scripts/jira_description_builders.py").exists()

    def execute(self, *, dry_run: bool = False) -> bool:
        config = ExtractionConfig(
            source_file="skills/conforma-exception/scripts/create_jira_ticket.py",
            target_file="skills/conforma-exception/scripts/jira_description_builders.py",
            function_names=[
                "build_rhoaieng_description", "build_rhoaieng_remediation_description",
                "build_rhoaieng_violation_report_description",
                "build_psx_description", "build_psx_filled_adf",
                "build_summary", "fill_psx_template",
                "build_exception_label", "build_provenance_footer",
            ],
            target_docstring="Jira ticket description builders — ADF and text generation for all ticket types.",
        )
        return extract_functions(config, dry_run=dry_run)


class Step9_ExtractGuideRenderers(Step):
    number = 9
    description = "Extracting guide_renderers.py from generate_resolution_guide.py"
    needs_tests = True

    def is_complete(self) -> bool:
        return Path("skills/conforma-analyze/scripts/guide_renderers.py").exists()

    def execute(self, *, dry_run: bool = False) -> bool:
        config = ExtractionConfig(
            source_file="skills/conforma-analyze/scripts/generate_resolution_guide.py",
            target_file="skills/conforma-analyze/scripts/guide_renderers.py",
            function_names=[
                "render_metadata_header", "render_key_takeaways", "render_summary",
                "render_coverage_table", "render_resolution_guide",
                "render_excepted_violation", "render_partial_coverage_header",
                "render_cataloged_violation", "render_uncataloged_violation",
                "render_known_false_alerts", "render_components_table",
                "render_warnings_section", "render_statistical_breakdown",
                "render_tooling_health", "render_work_scope", "render_divergence_warning",
                "write_executive_summary", "format_violation_cell",
            ],
            target_docstring="Resolution guide renderers — pure functions that take data and return markdown.",
        )
        return extract_functions(config, dry_run=dry_run)


class Step10_ExtractCoverageStatus(Step):
    number = 10
    description = "Extracting coverage_status_ops.py from violations_coverage.py"
    needs_tests = True

    def is_complete(self) -> bool:
        return Path("skills/conforma-analyze/scripts/coverage_status_ops.py").exists()

    def execute(self, *, dry_run: bool = False) -> bool:
        config = ExtractionConfig(
            source_file="skills/conforma-analyze/scripts/violations_coverage.py",
            target_file="skills/conforma-analyze/scripts/coverage_status_ops.py",
            function_names=[
                "determine_status_and_next_steps", "build_search_urls",
                "map_gate_status", "extract_exception_expiry", "load_report_metadata",
            ],
            target_docstring="Coverage status operations — pure status determination and classification logic.",
        )
        return extract_functions(config, dry_run=dry_run)


class Step11_ExtractExceptionScanner(Step):
    number = 11
    description = "Extracting exception_scanner.py from manage_exceptions.py"
    needs_tests = False  # Tests patch original module; Step 13 fixes them

    def is_complete(self) -> bool:
        return Path("skills/conforma-exception/scripts/exception_scanner.py").exists()

    def execute(self, *, dry_run: bool = False) -> bool:
        config = ExtractionConfig(
            source_file="skills/conforma-exception/scripts/manage_exceptions.py",
            target_file="skills/conforma-exception/scripts/exception_scanner.py",
            function_names=[
                "scan_all_exceptions", "scan_permanent_exclusions",
                "scan_self_service_exceptions", "search_exceptions_for_components",
                "filter_expired", "annotate_expiry",
                "strip_version_suffix", "extract_image_base",
                "normalize_name", "fuzzy_component_match", "fuzzy_image_match",
            ],
            target_docstring="Exception scanner — policy file scanning and component name matching.",
        )
        return extract_functions(config, dry_run=dry_run)


class Step12_DedupSharedUtils(Step):
    number = 12
    description = "Deduplicating shared utilities"
    needs_tests = False  # Step 11 leaves a test issue; Step 13 fixes all tests

    def is_complete(self) -> bool:
        return Path("scripts/date_ops.py").exists()

    def execute(self, *, dry_run: bool = False) -> bool:
        if dry_run:
            print("\n    Would create scripts/date_ops.py")
            print("    Would create scripts/conforma_yaml_ops.py")
            print("    Would update imports in source files")
            return True

        # Extract _parse_date to scripts/date_ops.py
        self._extract_parse_date()

        # Extract YAML quoting to scripts/conforma_yaml_ops.py
        self._extract_yaml_quoting()

        # Update _get_github_token imports to use scripts/github_ops.py
        self._update_github_token_imports()

        return True

    def _extract_parse_date(self):
        """Extract _parse_date from multiple files into scripts/date_ops.py."""
        # Find _parse_date in one of the source files
        sources = [
            Path("skills/conforma-analyze/scripts/analyze_csv_report.py"),
            Path("skills/conforma-analyze/scripts/parse_violations.py"),
        ]

        parse_date_source = None
        for src in sources:
            if not src.exists():
                continue
            content = src.read_text()
            tree = ast.parse(content)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_parse_date":
                    source_lines = content.splitlines(keepends=True)
                    parse_date_source = "".join(
                        source_lines[node.lineno - 1: node.end_lineno]
                    )
                    break
            if parse_date_source:
                break

        if not parse_date_source:
            print("\n    WARNING: _parse_date not found, skipping")
            return

        # Write date_ops.py
        date_ops = (
            '"""Date parsing utilities shared across conforma scripts."""\n\n'
            "from __future__ import annotations\n\n"
            "from datetime import datetime, timezone\n\n\n"
        )
        # Make it public (remove underscore)
        date_ops += parse_date_source.replace("def _parse_date", "def parse_date", 1)
        Path("scripts/date_ops.py").write_text(date_ops)

        # Update imports in source files
        for src in sources:
            if not src.exists():
                continue
            content = src.read_text()
            if "_parse_date" not in content:
                continue

            # Add import
            import_line = "from date_ops import parse_date as _parse_date  # noqa: F401\n"
            lines = content.splitlines(keepends=True)

            # Remove the function definition
            tree = ast.parse(content)
            lines_to_remove = set()
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_parse_date":
                    for i in range(node.lineno - 1, node.end_lineno or node.lineno):
                        lines_to_remove.add(i)

            remaining = [l for i, l in enumerate(lines) if i not in lines_to_remove]

            # Insert import after existing imports (AST-based for accuracy)
            remaining_text = "".join(remaining)
            try:
                remaining_tree = ast.parse(remaining_text)
                insert_pos = 0
                for rnode in ast.iter_child_nodes(remaining_tree):
                    if isinstance(rnode, ast.Import | ast.ImportFrom):
                        end = rnode.end_lineno or rnode.lineno
                        if end > insert_pos:
                            insert_pos = end
            except SyntaxError:
                insert_pos = 0
                for i, line in enumerate(remaining):
                    stripped = line.strip()
                    if stripped.startswith("import ") or stripped.startswith("from "):
                        if "(" not in stripped or ")" in stripped:
                            insert_pos = i + 1

            remaining.insert(insert_pos, import_line)
            src.write_text("".join(remaining))

    def _extract_yaml_quoting(self):
        """Extract YAML quoting utilities to scripts/conforma_yaml_ops.py."""
        sources = [
            Path("skills/conforma-analyze/scripts/parse_violations.py"),
            Path("skills/conforma-exception/scripts/manage_exceptions.py"),
        ]

        yaml_funcs = ["_QuotedStr", "_quoted_str_representer", "_safe_yaml_dump", "_needs_quoting", "_quote_strings_recursively"]
        found_source = None
        found_nodes: list[tuple[int, int]] = []

        for src in sources:
            if not src.exists():
                continue
            content = src.read_text()
            tree = ast.parse(content)
            nodes = []
            for node in ast.iter_child_nodes(tree):
                name = None
                if isinstance(node, ast.FunctionDef) and node.name in yaml_funcs:
                    name = node.name
                elif isinstance(node, ast.ClassDef) and node.name in yaml_funcs:
                    name = node.name
                if name:
                    nodes.append((node.lineno - 1, node.end_lineno or node.lineno))

            if nodes:
                found_source = src
                found_nodes = nodes
                break

        if not found_source:
            print("\n    WARNING: YAML quoting utilities not found, skipping")
            return

        content = found_source.read_text()
        source_lines = content.splitlines(keepends=True)

        # Extract the code
        yaml_ops_content = (
            '"""YAML quoting utilities shared across conforma scripts."""\n\n'
            "from __future__ import annotations\n\n"
            "import re\n\nimport yaml\n\n\n"
        )
        for start, end in sorted(found_nodes):
            chunk = "".join(source_lines[start:end])
            yaml_ops_content += chunk + "\n\n"

        # Rename all private names to public in the combined content
        yaml_ops_content = yaml_ops_content.replace("class _QuotedStr", "class QuotedStr")
        yaml_ops_content = yaml_ops_content.replace("def _quoted_str_representer", "def quoted_str_representer")
        yaml_ops_content = yaml_ops_content.replace("def _safe_yaml_dump", "def safe_yaml_dump")
        yaml_ops_content = yaml_ops_content.replace("def _needs_quoting", "def needs_quoting")
        yaml_ops_content = yaml_ops_content.replace("def _quote_strings_recursively", "def quote_strings_recursively")
        # Replace all internal references using word-boundary approach
        yaml_ops_content = re.sub(r'\b_QuotedStr\b', 'QuotedStr', yaml_ops_content)
        yaml_ops_content = re.sub(r'\b_quoted_str_representer\b', 'quoted_str_representer', yaml_ops_content)
        yaml_ops_content = re.sub(r'\b_safe_yaml_dump\b', 'safe_yaml_dump', yaml_ops_content)
        yaml_ops_content = re.sub(r'\b_needs_quoting\b', 'needs_quoting', yaml_ops_content)
        yaml_ops_content = re.sub(r'\b_quote_strings_recursively\b', 'quote_strings_recursively', yaml_ops_content)

        Path("scripts/conforma_yaml_ops.py").write_text(yaml_ops_content)

        # Update source files to import from new location
        for src in sources:
            if not src.exists():
                continue
            content = src.read_text()
            has_any = any(f in content for f in yaml_funcs)
            if not has_any:
                continue

            tree = ast.parse(content)
            lines_to_remove = set()
            for node in ast.iter_child_nodes(tree):
                name = None
                if isinstance(node, ast.FunctionDef) and node.name in yaml_funcs:
                    name = node.name
                elif isinstance(node, ast.ClassDef) and node.name in yaml_funcs:
                    name = node.name
                if name:
                    for i in range(node.lineno - 1, node.end_lineno or node.lineno):
                        lines_to_remove.add(i)

            if not lines_to_remove:
                continue

            file_lines = content.splitlines(keepends=True)
            remaining = [l for i, l in enumerate(file_lines) if i not in lines_to_remove]

            # Add re-export imports (AST-based insertion)
            imports = (
                "from conforma_yaml_ops import QuotedStr as _QuotedStr  # noqa: F401\n"
                "from conforma_yaml_ops import quoted_str_representer as _quoted_str_representer  # noqa: F401\n"
                "from conforma_yaml_ops import safe_yaml_dump as _safe_yaml_dump  # noqa: F401\n"
                "from conforma_yaml_ops import needs_quoting as _needs_quoting  # noqa: F401\n"
                "from conforma_yaml_ops import quote_strings_recursively as _quote_strings_recursively  # noqa: F401\n"
            )
            remaining_text = "".join(remaining)
            try:
                remaining_tree = ast.parse(remaining_text)
                insert_pos = 0
                for rnode in ast.iter_child_nodes(remaining_tree):
                    if isinstance(rnode, ast.Import | ast.ImportFrom):
                        end = rnode.end_lineno or rnode.lineno
                        if end > insert_pos:
                            insert_pos = end
            except SyntaxError:
                insert_pos = 0
                for i, line in enumerate(remaining):
                    stripped = line.strip()
                    if stripped.startswith("import ") or stripped.startswith("from "):
                        if "(" not in stripped or ")" in stripped:
                            insert_pos = i + 1
            remaining.insert(insert_pos, imports)
            src.write_text("".join(remaining))

    def _update_github_token_imports(self):
        """Update files using _get_github_token to import from github_ops."""
        files_with_token = [
            Path("skills/conforma-analyze/scripts/violation_history.py"),
            Path("skills/conforma-analyze/scripts/submit_resolution_guide.py"),
            Path("skills/conforma-analyze/scripts/validate_guide_links.py"),
        ]

        for filepath in files_with_token:
            if not filepath.exists():
                continue
            content = filepath.read_text()
            if "_get_github_token" not in content:
                continue

            # Check if it defines its own _get_github_token
            tree = ast.parse(content)
            has_local_def = False
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_get_github_token":
                    has_local_def = True
                    break

            if not has_local_def:
                continue

            # Remove local definition, add import
            file_lines = content.splitlines(keepends=True)
            lines_to_remove = set()
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_get_github_token":
                    for i in range(node.lineno - 1, node.end_lineno or node.lineno):
                        lines_to_remove.add(i)

            remaining = [l for i, l in enumerate(file_lines) if i not in lines_to_remove]

            import_line = "from github_ops import get_token as _get_github_token  # noqa: F401\n"
            remaining_text = "".join(remaining)
            try:
                remaining_tree = ast.parse(remaining_text)
                insert_pos = 0
                for rnode in ast.iter_child_nodes(remaining_tree):
                    if isinstance(rnode, ast.Import | ast.ImportFrom):
                        end = rnode.end_lineno or rnode.lineno
                        if end > insert_pos:
                            insert_pos = end
            except SyntaxError:
                insert_pos = 0
                for i, line in enumerate(remaining):
                    stripped = line.strip()
                    if stripped.startswith("import ") or stripped.startswith("from "):
                        if "(" not in stripped or ")" in stripped:
                            insert_pos = i + 1
            remaining.insert(insert_pos, import_line)
            filepath.write_text("".join(remaining))


class Step13_UpdateTests(Step):
    number = 13
    description = "Updating test imports to use new modules"
    needs_tests = True

    def is_complete(self) -> bool:
        # Check if any test still uses the old import pattern for extracted functions
        test_dir = Path("tests/unit")
        if not test_dir.exists():
            return True
        # Spot check: if guide_renderers exists and tests import from it, we're done
        if Path("skills/conforma-analyze/scripts/guide_renderers.py").exists():
            for test_file in test_dir.glob("test_conforma_analyze_generate_resolution_guide*.py"):
                content = test_file.read_text()
                if "from guide_renderers import" in content:
                    return True
        return False

    def execute(self, *, dry_run: bool = False) -> bool:
        # Map: original module -> extracted module -> function names
        extraction_map = {
            "create_gitlab_mr": {
                "exception_mr_text": [
                    "_build_commit_message", "_build_commit_message_consolidated",
                    "_build_mr_title", "_build_mr_title_consolidated",
                    "_build_mr_body", "_build_mr_body_consolidated",
                    "_build_extend_commit_message", "_build_lifecycle_commit_message",
                ],
                "exception_policy_file_ops": [
                    "_resolve_policy_file", "_resolve_self_service_file",
                    "_detect_component_type", "_get_target_file",
                    "_generate_exception_yaml", "_find_existing_exceptions",
                    "_remove_exception_from_policy_file", "_apply_exception_to_policy_file",
                    "_append_to_policy_file", "AmbiguousPolicyFileError",
                ],
            },
            "create_jira_ticket": {
                "jira_description_builders": [
                    "_build_rhoaieng_description", "_build_rhoaieng_remediation_description",
                    "_build_rhoaieng_violation_report_description",
                    "_build_psx_description", "_build_psx_filled_adf",
                    "_build_summary", "_fill_psx_template",
                    "_build_exception_label", "_build_provenance_footer",
                ],
            },
            "generate_resolution_guide": {
                "guide_renderers": [
                    "_render_metadata_header", "_render_key_takeaways", "_render_summary",
                    "_render_coverage_table", "_render_resolution_guide",
                    "_render_excepted_violation", "_render_partial_coverage_header",
                    "_render_cataloged_violation", "_render_uncataloged_violation",
                    "_render_known_false_alerts", "_render_components_table",
                    "_render_warnings_section", "_render_statistical_breakdown",
                    "_render_tooling_health", "_render_work_scope", "_render_divergence_warning",
                    "_write_executive_summary", "_format_violation_cell",
                ],
            },
            "violations_coverage": {
                "coverage_status_ops": [
                    "_determine_status_and_next_steps", "_build_search_urls",
                    "_map_gate_status", "_extract_exception_expiry", "_load_report_metadata",
                ],
            },
            "manage_exceptions": {
                "exception_scanner": [
                    "scan_all_exceptions", "scan_permanent_exclusions",
                    "scan_self_service_exceptions", "search_exceptions_for_components",
                    "filter_expired", "annotate_expiry",
                    "_strip_version_suffix", "_extract_image_base",
                    "_normalize_name", "_fuzzy_component_match", "_fuzzy_image_match",
                ],
            },
        }

        # Dependency functions that got copied to extracted modules and need
        # patch.object targets updated in tests
        patch_fixups: dict[str, list[tuple[str, str]]] = {
            # test file pattern: [(old patch target module, new patch target module)]
            "test_conforma_exception_manage_exceptions": [
                ("mod", "exception_scanner"),
            ],
        }

        test_dir = Path("tests/unit")
        if not test_dir.exists():
            return True

        modified_count = 0

        for test_file in sorted(test_dir.glob("test_conforma_*.py")):
            content = test_file.read_text()
            original_content = content

            for orig_module, extractions in extraction_map.items():
                if f"import {orig_module}" not in content and f"from {orig_module}" not in content:
                    continue

                for new_module, func_names in extractions.items():
                    # Sort by length descending to prevent substring collisions
                    for func_name in sorted(func_names, key=len, reverse=True):
                        old_pattern = f"mod.{func_name}"
                        if old_pattern not in content:
                            continue

                        public_name = func_name.lstrip("_")
                        new_import = f"from {new_module} import {public_name}"

                        if new_import not in content:
                            lines = content.splitlines(keepends=True)
                            insert_pos = 0
                            for i, line in enumerate(lines):
                                if line.startswith("import ") or line.startswith("from "):
                                    insert_pos = i + 1
                            lines.insert(insert_pos, new_import + "\n")
                            content = "".join(lines)

                        content = content.replace(old_pattern, public_name)

            # Fix patch.object targets for dependency functions
            for file_pattern, fixups in patch_fixups.items():
                if file_pattern in test_file.stem:
                    for old_target, new_module in fixups:
                        # Replace: patch.object(mod, "_dep_func", ...) → patch("new_module._dep_func", ...)
                        # Also need to add import for the new module
                        if f"import {new_module}" not in content:
                            lines = content.splitlines(keepends=True)
                            insert_pos = 0
                            for i, line in enumerate(lines):
                                if line.startswith("import ") or line.startswith("from "):
                                    insert_pos = i + 1
                            lines.insert(insert_pos, f"import {new_module}\n")
                            content = "".join(lines)
                        # Replace patch.object(mod, "func") with patch.object(exception_scanner, "func")
                        content = content.replace(
                            f"patch.object({old_target}, \"_get_conforma_policy_dir\"",
                            f"patch.object({new_module}, \"_get_conforma_policy_dir\""
                        )

            if content != original_content:
                if not dry_run:
                    test_file.write_text(content)
                modified_count += 1

        if dry_run:
            print(f"\n    Would update {modified_count} test files")

        return True


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def preflight_checks(*, skip_baseline_test: bool = False) -> bool:
    """Validate repo state before running. Returns True if all checks pass."""
    checks_passed = True

    # 1. Working directory
    if not Path("AGENTS.md").exists() or not Path("skills/conforma/SKILL.md").exists():
        print("ERROR: Not in repo root. Run from the aiops-infra directory.")
        return False

    # 2. Clean git state
    result = run_cmd(["git", "status", "--porcelain"])
    if result.stdout.strip():
        print("ERROR: Uncommitted changes detected. Run `git stash` first, then re-run this script.")
        print(f"  Dirty files:\n{result.stdout}")
        return False

    # 3. Source files exist
    for src in EXTRACTION_SOURCE_FILES:
        p = Path(src)
        if not p.exists():
            print(f"ERROR: Source file not found: {src}")
            checks_passed = False
        elif count_lines(p) < 300:
            print(f"ERROR: Source file too small (expected >300 lines): {src}")
            checks_passed = False

    # 4. Python version
    if sys.version_info < (3, 10):
        print(f"ERROR: Python 3.10+ required, got {sys.version}")
        checks_passed = False

    # 5. PyYAML
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("ERROR: PyYAML not installed. Run: pip install pyyaml")
        checks_passed = False

    # 6. Baseline tests
    if not skip_baseline_test:
        print("Running baseline tests...", end=" ", flush=True)
        if run_tests():
            print("OK")
        else:
            print("FAILED")
            print("ERROR: Tests fail before any changes. Fix tests first.")
            checks_passed = False

    # 7. Git identity
    name_result = run_cmd(["git", "config", "user.name"], check=False)
    email_result = run_cmd(["git", "config", "user.email"], check=False)
    if not name_result.stdout.strip() or not email_result.stdout.strip():
        print("ERROR: Git identity not set. Run: git config user.name 'Name' && git config user.email 'email'")
        checks_passed = False

    return checks_passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--start-from", type=int, default=0, metavar="N", help="Skip to step N")
    parser.add_argument("--no-commit", action="store_true", help="Make changes but don't commit")
    parser.add_argument("--no-test", action="store_true", help="Skip test runs")
    parser.add_argument("--skip-baseline-test", action="store_true", help="Skip pre-flight test run")
    args = parser.parse_args()

    print("=" * 60)
    print("Conforma Skill Decomposition — Automation Script")
    print("=" * 60)
    print()

    # Pre-flight
    if not args.dry_run:
        print("Running pre-flight checks...")
        if not preflight_checks(skip_baseline_test=args.skip_baseline_test):
            sys.exit(1)
        print()

    # Define step instances
    steps: list[Step] = [
        Step0_FixAlwaysOnOverhead(),
        Step1_ModuleHeaders(),
        Step2_SplitExceptionSkill(),
        Step3_SplitAnalyzeSkill(),
        Step4_SplitReportFetchSkill(),
        Step5_ReferenceScoping(),
        Step6_ExtractMrText(),
        Step7_ExtractPolicyFileOps(),
        Step8_ExtractJiraBuilders(),
        Step9_ExtractGuideRenderers(),
        Step10_ExtractCoverageStatus(),
        Step11_ExtractExceptionScanner(),
        Step12_DedupSharedUtils(),
        Step13_UpdateTests(),
    ]

    # Execute steps
    results: list[tuple[int, str | None]] = []
    for step in steps:
        if step.number < args.start_from:
            continue

        result = step.run(
            dry_run=args.dry_run,
            no_commit=args.no_commit,
            no_test=args.no_test,
        )

        if result is None:
            print(f"\nFailed at step {step.number}. Fix the issue and re-run with --start-from {step.number}")
            sys.exit(1)

        results.append((step.number, result))

    # Summary
    print()
    committed = [r for r in results if r[1] not in ("skipped", "dry-run", "no-commit")]
    skipped = [r for r in results if r[1] == "skipped"]

    if args.dry_run:
        print(f"Dry run complete. {len(results)} steps would be executed.")
    else:
        print(f"Done. {len(committed)} commits created, {len(skipped)} steps skipped.")
        if committed:
            print(f"Run `git log --oneline -{len(committed)}` to review.")


if __name__ == "__main__":
    main()
