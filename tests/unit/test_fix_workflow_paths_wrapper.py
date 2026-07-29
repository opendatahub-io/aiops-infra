"""Tests for fix_workflow_paths.py --rewrite-to-wrapper and --validate-wrapper modes."""

from __future__ import annotations

import pytest

import fix_workflow_paths as fwp


class TestRewritePatternA:
    def test_inline_r_prefix(self):
        content = (
            "```bash\n"
            '_R="$(grep \'^aiops_infra_root:\' ~/.conforma/.conforma-active/context.yaml | cut -d\' \' -f2-)" '
            '&& python3 "$_R/scripts/foo.py" --arg1 val\n'
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert "~/.conforma/bin/conforma_run.sh scripts/foo.py --arg1 val" in result
        assert len(changes) == 1
        assert changes[0][0] == "A"

    def test_skills_path(self):
        content = (
            "```bash\n"
            '_R="$(grep \'^aiops_infra_root:\' ~/.conforma/.conforma-active/context.yaml | cut -d\' \' -f2-)" '
            '&& python3 "$_R/skills/conforma-analyze/scripts/bar.py"\n'
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert "~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/bar.py" in result
        assert len(changes) == 1

    def test_preserves_indentation(self):
        content = (
            "```bash\n"
            '   _R="$(grep \'^aiops_infra_root:\' ~/.conforma/.conforma-active/context.yaml | cut -d\' \' -f2-)" '
            '&& python3 "$_R/scripts/foo.py"\n'
            "```\n"
        )
        result, _ = fwp.rewrite_to_wrapper_in_file(content)
        assert "   ~/.conforma/bin/conforma_run.sh scripts/foo.py" in result


class TestRewritePatternB:
    def test_step0_bootstrap(self):
        content = (
            "```bash\n"
            '_R="${AIOPS_INFRA_ROOT:-$(python3 -c \'from _repo_root import REPO_ROOT; '
            "print(REPO_ROOT)' 2>/dev/null || git rev-parse --show-toplevel 2>/dev/null)}\"\n"
            'python3 "$_R/scripts/init_conforma_run.py" "<query>"\n'
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert "[ -x ~/.conforma/bin/conforma_run.sh ]" in result
        assert '~/.conforma/bin/conforma_run.sh scripts/init_conforma_run.py "<query>"' in result
        assert len(changes) == 1
        assert changes[0][0] == "B"

    def test_step0_with_set_args(self):
        content = (
            "```bash\n"
            '_R="${AIOPS_INFRA_ROOT:-$(python3 -c \'from _repo_root import REPO_ROOT; '
            "print(REPO_ROOT)' 2>/dev/null || git rev-parse --show-toplevel 2>/dev/null)}\"\n"
            'python3 "$_R/scripts/init_conforma_run.py" "<text>" --set violation_code "<code>"\n'
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert '--set violation_code "<code>"' in result
        assert len(changes) == 1


class TestRewritePatternC:
    def test_heredoc_block(self):
        content = (
            "```bash\n"
            '_ROOT="${AIOPS_INFRA_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null)}"\n'
            '[ -z "$_ROOT" ] && _ROOT="$HOME/.local/share/aiops-infra"\n'
            '[ -f "$_ROOT/pyproject.toml" ] || { echo "ERROR"; exit 1; }\n'
            '_RUNDIR="$HOME/.conforma/$(date -u +%Y%m%dT%H%M%SZ)"\n'
            'mkdir -p "$_RUNDIR"\n'
            'cat > "$_RUNDIR/context.yaml" << EOF\n'
            "aiops_infra_root: $_ROOT\n"
            "run:\n"
            "  created_at: $(date)\n"
            "  run_dir: ${_RUNDIR}\n"
            "steps: {}\n"
            "EOF\n"
            'ln -sfn "$_RUNDIR" "$HOME/.conforma/.conforma-active"\n'
            'echo "aiops_infra_root=$_ROOT"\n'
            'echo "run_dir=$_RUNDIR"\n'
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert "[ -x ~/.conforma/bin/conforma_run.sh ]" in result
        assert "scripts/init_conforma_run.py" in result
        assert "_ROOT=" not in result.split("```")[1]
        assert "heredoc" not in result
        assert len(changes) == 1
        assert changes[0][0] == "C"


class TestRewriteBarePaths:
    def test_bare_python3_scripts(self):
        content = (
            "```bash\n"
            "python3 scripts/foo.py --arg\n"
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert "~/.conforma/bin/conforma_run.sh scripts/foo.py --arg" in result
        assert len(changes) == 1
        assert changes[0][0] == "bare"

    def test_bare_python3_skills(self):
        content = (
            "```bash\n"
            "python3 skills/conforma-report-fetch/scripts/fetch.py --output /tmp/out.json\n"
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert "~/.conforma/bin/conforma_run.sh skills/conforma-report-fetch/scripts/fetch.py" in result


class TestSkips:
    def test_already_migrated_skipped(self):
        content = (
            "```bash\n"
            "~/.conforma/bin/conforma_run.sh scripts/foo.py\n"
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert result == content
        assert len(changes) == 0

    def test_outside_code_block_skipped(self):
        content = (
            '_R="$(grep \'^aiops_infra_root:\' ~/.conforma/.conforma-active/context.yaml | cut -d\' \' -f2-)" '
            '&& python3 "$_R/scripts/foo.py"\n'
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert result == content
        assert len(changes) == 0

    def test_absolute_path_skipped(self):
        content = (
            "```bash\n"
            "python3 ~/scripts/foo.py --arg\n"
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert result == content
        assert len(changes) == 0


class TestValidateWrapper:
    def test_catches_pattern_a(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text(
            "```bash\n"
            '_R="$(grep \'^aiops_infra_root:\' ~/.conforma/.conforma-active/context.yaml | cut -d\' \' -f2-)" '
            '&& python3 "$_R/scripts/foo.py"\n'
            "```\n"
        )
        content = md.read_text()
        in_code = False
        for line in content.split("\n"):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code and fwp._PATTERN_A_RE.match(line):
                assert True
                return
        pytest.fail("Pattern A not detected")

    def test_passes_clean_file(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text(
            "```bash\n"
            "~/.conforma/bin/conforma_run.sh scripts/foo.py\n"
            "```\n"
        )
        content = md.read_text()
        in_code = False
        for line in content.split("\n"):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                assert not fwp._PATTERN_A_RE.match(line)
                assert not fwp._PATTERN_C_START_RE.match(line)


class TestMultiplePatterns:
    def test_mixed_patterns_in_one_file(self):
        content = (
            "Step 0:\n"
            "```bash\n"
            '_R="${AIOPS_INFRA_ROOT:-$(python3 -c \'from _repo_root import REPO_ROOT; '
            "print(REPO_ROOT)' 2>/dev/null || git rev-parse --show-toplevel 2>/dev/null)}\"\n"
            'python3 "$_R/scripts/init_conforma_run.py" "rhoai-3.5"\n'
            "```\n"
            "\n"
            "Step 1:\n"
            "```bash\n"
            '_R="$(grep \'^aiops_infra_root:\' ~/.conforma/.conforma-active/context.yaml | cut -d\' \' -f2-)" '
            '&& python3 "$_R/scripts/resolve_release_context.py"\n'
            "```\n"
        )
        result, changes = fwp.rewrite_to_wrapper_in_file(content)
        assert len(changes) == 2
        assert changes[0][0] == "B"
        assert changes[1][0] == "A"
        assert "[ -x ~/.conforma/bin/conforma_run.sh ]" in result
        assert "~/.conforma/bin/conforma_run.sh scripts/resolve_release_context.py" in result
