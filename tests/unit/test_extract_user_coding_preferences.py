"""Tests for scripts/extract_user_coding_preferences.py."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from extract_user_coding_preferences import (
    ProposedRule,
    _find_terminology_swaps,
    _strip_system_tags,
    append_to_agents_md,
    deduplicate,
    detect_corrections_regex,
    parse_transcripts,
    save_proposals,
    score_and_split,
)


class TestStripSystemTags:
    def test_extracts_user_query(self):
        text = "<timestamp>Monday</timestamp>\n<user_query>\nfix MR to Merge Request\n</user_query>"
        assert _strip_system_tags(text) == "fix MR to Merge Request"

    def test_removes_system_reminder(self):
        text = "<system_reminder>some reminder</system_reminder>\nhello world"
        assert _strip_system_tags(text) == "hello world"

    def test_plain_text_unchanged(self):
        text = "change all MR references to Merge Request"
        assert _strip_system_tags(text) == text

    def test_nested_tags_removed(self):
        text = (
            "<user_info>OS: linux</user_info>\n"
            "<timestamp>Sunday</timestamp>\n"
            "<user_query>use Merge Request not MR</user_query>"
        )
        assert _strip_system_tags(text) == "use Merge Request not MR"


class TestRegexDetection:
    def test_use_x_not_y(self):
        messages = [{"session_id": "abc", "message": 'use "Merge Request" not "MR"'}]
        results = detect_corrections_regex(messages)
        assert len(results) >= 1
        found = [r for r in results if r.prefer and "Merge Request" in r.prefer]
        assert found
        assert found[0].avoid == "MR"
        assert found[0].confidence == "high"
        assert found[0].category == "terminology"

    def test_change_x_to_y(self):
        messages = [{"session_id": "def", "message": "change MR to Merge Request everywhere"}]
        results = detect_corrections_regex(messages)
        assert len(results) >= 1
        found = [r for r in results if r.prefer and "Merge Request" in r.prefer]
        assert found

    def test_replace_x_to_y(self):
        messages = [{"session_id": "ghi", "message": "replace all instances of MRs to Merge Requests"}]
        results = detect_corrections_regex(messages)
        assert len(results) >= 1

    def test_prohibition(self):
        messages = [{"session_id": "jkl", "message": "never use abbreviations in documentation"}]
        results = detect_corrections_regex(messages)
        assert len(results) >= 1
        assert results[0].category == "behavior"

    def test_always_preference(self):
        messages = [{"session_id": "mno", "message": "always write tests for new scripts"}]
        results = detect_corrections_regex(messages)
        assert len(results) >= 1
        assert results[0].category == "behavior"

    def test_frustration_signal(self):
        messages = [{"session_id": "pqr", "message": "I already told you to use Merge Request!"}]
        results = detect_corrections_regex(messages)
        assert len(results) >= 1

    def test_short_message_ignored(self):
        messages = [{"session_id": "stu", "message": "ok"}]
        results = detect_corrections_regex(messages)
        assert len(results) == 0

    def test_long_message_ignored(self):
        messages = [{"session_id": "vwx", "message": "x" * 1001}]
        results = detect_corrections_regex(messages)
        assert len(results) == 0

    def test_non_correction_not_detected(self):
        messages = [{"session_id": "yz", "message": "what is the status of the build?"}]
        results = detect_corrections_regex(messages)
        assert len(results) == 0


class TestFindTerminologySwaps:
    def test_single_word_swap(self):
        removed = "Open the MR in GitLab"
        added = "Open the Merge Request in GitLab"
        # Lines have different word counts, so no swap detected
        assert _find_terminology_swaps(removed, added) == []

    def test_same_word_count_swap(self):
        removed = "Check the MRs status now"
        added = "Check the PRs status now"
        swaps = _find_terminology_swaps(removed, added)
        assert ("MRs", "PRs") in swaps

    def test_too_many_differences(self):
        removed = "a b c d"
        added = "e f g h"
        assert _find_terminology_swaps(removed, added) == []

    def test_identical_lines(self):
        removed = "no change here today"
        added = "no change here today"
        assert _find_terminology_swaps(removed, added) == []

    def test_rejects_code_tokens(self):
        removed = "return True from function"
        added = "return False from function"
        assert _find_terminology_swaps(removed, added) == []

    def test_rejects_short_tokens(self):
        removed = "use a for this"
        added = "use b for this"
        assert _find_terminology_swaps(removed, added) == []

    def test_rejects_too_short_lines(self):
        removed = "MR PR"
        added = "Merge Request"
        assert _find_terminology_swaps(removed, added) == []


class TestDeduplicate:
    def test_removes_existing_rule(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text('- Always use "Merge Request" (never "MR")\n')

        proposals = [
            ProposedRule(
                category="terminology",
                rule='Always use "Merge Request" (never "MR")',
                prefer="Merge Request",
                avoid="MR",
            )
        ]
        new, _ = deduplicate(proposals, agents_md)
        assert len(new) == 0

    def test_keeps_new_rule(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Empty\n")

        proposals = [
            ProposedRule(
                category="terminology",
                rule='Use "violations" not "rules"',
                prefer="violations",
                avoid="rules",
            )
        ]
        new, _ = deduplicate(proposals, agents_md)
        assert len(new) == 1

    def test_merges_duplicate_proposals(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Empty\n")

        proposals = [
            ProposedRule(
                category="terminology",
                rule='Use "Merge Request"',
                prefer="Merge Request",
                avoid="MR",
                sources=[{"session": "s1", "user_said": "fix MR"}],
            ),
            ProposedRule(
                category="terminology",
                rule='Use "Merge Request"',
                prefer="Merge Request",
                avoid="MR",
                sources=[{"session": "s2", "user_said": "change MR to Merge Request"}],
            ),
        ]
        new, _ = deduplicate(proposals, agents_md)
        assert len(new) == 1
        assert new[0].evidence_count == 2
        assert len(new[0].sources) == 2


class TestScoreAndSplit:
    def test_high_confidence_terminology_auto_adds(self):
        proposals = [
            ProposedRule(
                category="terminology",
                rule='Use "Merge Request"',
                prefer="Merge Request",
                avoid="MR",
                confidence="high",
                evidence_count=3,
            )
        ]
        auto, review = score_and_split(proposals)
        assert len(auto) == 1
        assert len(review) == 0

    def test_behavior_always_queued(self):
        proposals = [
            ProposedRule(
                category="behavior",
                rule="Never auto-submit",
                confidence="high",
                evidence_count=5,
            )
        ]
        auto, review = score_and_split(proposals)
        assert len(auto) == 0
        assert len(review) == 1

    def test_single_occurrence_queued(self):
        proposals = [
            ProposedRule(
                category="terminology",
                rule='Use "X" not "Y"',
                prefer="X",
                avoid="Y",
                confidence="high",
                evidence_count=1,
            )
        ]
        auto, review = score_and_split(proposals)
        assert len(auto) == 0
        assert len(review) == 1

    def test_no_prefer_queued(self):
        proposals = [
            ProposedRule(
                category="terminology",
                rule="Some vague rule",
                confidence="high",
                evidence_count=3,
            )
        ]
        auto, review = score_and_split(proposals)
        assert len(auto) == 0
        assert len(review) == 1


class TestAppendToAgentsMd:
    def test_appends_terminology_rule(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# Project\n\n"
            "### Terminology\n\n"
            '- Use "Merge Request" always\n\n'
            "### Code Style\n\n"
            "- Some code rule\n"
        )
        rules = [
            ProposedRule(
                category="terminology",
                rule='Always use "violations"',
                prefer="violations",
                avoid="rules",
                confidence="high",
                evidence_count=2,
            )
        ]
        added = append_to_agents_md(rules, agents_md)
        assert added == 1
        content = agents_md.read_text()
        assert '"violations"' in content
        assert '"rules"' in content

    def test_no_section_no_write(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Empty file\n")
        rules = [
            ProposedRule(
                category="terminology",
                rule="some rule",
                prefer="X",
                avoid="Y",
            )
        ]
        added = append_to_agents_md(rules, agents_md)
        assert added == 0


class TestSaveProposals:
    def test_creates_new_file(self, tmp_path):
        output = tmp_path / "proposals.yaml"
        proposals = [
            ProposedRule(
                category="behavior",
                rule="Never auto-submit",
                confidence="medium",
                evidence_count=1,
                sources=[{"session": "abc", "user_said": "don't submit without asking"}],
            )
        ]
        save_proposals(proposals, output)
        assert output.exists()
        import yaml
        data = yaml.safe_load(output.read_text())
        assert len(data["proposed_rules"]) == 1
        assert data["proposed_rules"][0]["rule"] == "Never auto-submit"

    def test_merges_with_existing(self, tmp_path):
        output = tmp_path / "proposals.yaml"
        import yaml
        output.write_text(
            yaml.dump({"proposed_rules": [{"category": "behavior", "rule": "Existing rule", "evidence_count": 1}]})
        )
        proposals = [
            ProposedRule(category="behavior", rule="New rule", confidence="medium")
        ]
        save_proposals(proposals, output)
        data = yaml.safe_load(output.read_text())
        assert len(data["proposed_rules"]) == 2


class TestParseTranscripts:
    def test_parses_jsonl(self, tmp_path):
        tdir = tmp_path / "transcripts" / "session-1"
        tdir.mkdir(parents=True)
        jsonl = tdir / "session-1.jsonl"
        records = [
            {"role": "user", "message": {"content": [{"type": "text", "text": "<user_query>fix MR to Merge Request</user_query>"}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
            {"role": "user", "message": {"content": [{"type": "text", "text": "<user_query>looks good</user_query>"}]}},
        ]
        jsonl.write_text("\n".join(json.dumps(r) for r in records))

        results = parse_transcripts([tmp_path / "transcripts"])
        assert len(results) == 2
        assert results[0]["message"] == "fix MR to Merge Request"
        assert results[0]["session_id"] == "session-1"

    def test_skips_subagents(self, tmp_path):
        tdir = tmp_path / "transcripts" / "session-1" / "subagents"
        tdir.mkdir(parents=True)
        jsonl = tdir / "sub-1.jsonl"
        jsonl.write_text(json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": "test"}]}}))

        results = parse_transcripts([tmp_path / "transcripts"])
        assert len(results) == 0

    def test_respects_since_hours(self, tmp_path):
        import time

        tdir = tmp_path / "transcripts" / "old-session"
        tdir.mkdir(parents=True)
        jsonl = tdir / "old-session.jsonl"
        jsonl.write_text(json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": "old msg"}]}}))
        old_time = time.time() - 86400
        os.utime(jsonl, (old_time, old_time))

        results = parse_transcripts([tmp_path / "transcripts"], since_hours=1)
        assert len(results) == 0


import os
