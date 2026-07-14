"""Tests for tests/check_workflow_determinism.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_workflow_determinism as hook


class TestExtractBashBlocks:
    def test_extracts_single_block(self):
        content = "### Step 1\n\n```bash\necho hello\n```\n"
        blocks = hook.extract_bash_blocks(content)
        assert len(blocks) == 1
        assert "Step 1" in blocks[0]["step"]

    def test_extracts_comments_from_block(self):
        content = "### Step 7\n\n```bash\n# With Slack\necho yes\n```\n"
        blocks = hook.extract_bash_blocks(content)
        assert "# With Slack" in blocks[0]["comments"]

    def test_handles_no_bash_blocks(self):
        content = "# Workflow\n\nJust some text.\n"
        blocks = hook.extract_bash_blocks(content)
        assert blocks == []

    def test_multiple_blocks_in_same_step(self):
        content = (
            "### Step 7\n\n"
            "```bash\n# With Slack\necho yes\n```\n\n"
            "```bash\n# Without Slack\necho no\n```\n"
        )
        blocks = hook.extract_bash_blocks(content)
        assert len(blocks) == 2
        assert all("Step 7" in b["step"] for b in blocks)


class TestFindConditionalPairs:
    def test_detects_with_without_pair(self):
        blocks = [
            {"step": "### Step 7", "comments": ["# With Slack"], "line_no": 10},
            {"step": "### Step 7", "comments": ["# Without Slack"], "line_no": 15},
        ]
        pairs = hook.find_conditional_pairs(blocks)
        assert len(pairs) == 1
        assert pairs[0]["topic"] == "slack"

    def test_clean_workflow_passes(self):
        blocks = [
            {"step": "### Step 1", "comments": [], "line_no": 5},
            {"step": "### Step 2", "comments": [], "line_no": 10},
        ]
        pairs = hook.find_conditional_pairs(blocks)
        assert pairs == []

    def test_with_without_in_different_steps_ok(self):
        blocks = [
            {"step": "### Step 1", "comments": ["# With Slack"], "line_no": 5},
            {"step": "### Step 2", "comments": ["# Without Slack"], "line_no": 10},
        ]
        pairs = hook.find_conditional_pairs(blocks)
        assert pairs == []

    def test_ignores_non_conditional_comments(self):
        blocks = [
            {"step": "### Step 3", "comments": ["# To customize:"], "line_no": 5},
            {"step": "### Step 3", "comments": ["# Alternative approach:"], "line_no": 10},
        ]
        pairs = hook.find_conditional_pairs(blocks)
        assert pairs == []


class TestCheckFile:
    def test_clean_file(self, tmp_path):
        f = tmp_path / "clean.md"
        f.write_text("### Step 1\n\n```bash\necho hi\n```\n")
        with patch.object(hook, "REPO_ROOT", tmp_path):
            errors = hook.check_file(f)
        assert errors == []

    def test_detects_paired_blocks(self, tmp_path):
        f = tmp_path / "bad.md"
        f.write_text(
            "### Step 7\n\n"
            "```bash\n# With Slack\necho yes\n```\n\n"
            "```bash\n# Without Slack\necho no\n```\n"
        )
        with patch.object(hook, "REPO_ROOT", tmp_path):
            errors = hook.check_file(f)
        assert len(errors) == 1
        assert "With slack" in errors[0] or "With Slack" in errors[0].lower() or "slack" in errors[0].lower()


class TestDiscoverWorkflowFiles:
    def test_discovers_workflow_files(self):
        files = hook.discover_workflow_files()
        assert len(files) > 0
        assert all("/workflows/" in str(f) for f in files)
        assert all(str(f).endswith(".md") for f in files)


class TestMain:
    def test_passes_on_clean_codebase(self):
        ret = hook.main()
        assert ret == 0
