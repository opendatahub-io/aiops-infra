"""Tests for scripts/slack_ops.py (slackdump backend)."""

from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

import slack_ops


@pytest.fixture
def fake_slackdump_cache(tmp_path, monkeypatch):
    """Set up a fake slackdump cache directory with auth file."""
    cache_dir = tmp_path / ".cache" / "slackdump"
    cache_dir.mkdir(parents=True)
    (cache_dir / "redhat-internal.slack.com.bin").write_bytes(b"fake-auth")
    (cache_dir / "workspace.txt").write_text("redhat-internal.slack.com")
    monkeypatch.setattr(slack_ops, "SLACKDUMP_CACHE_DIR", cache_dir)
    return cache_dir


@pytest.fixture
def mock_slackdump_binary(monkeypatch):
    """Mock shutil.which to find slackdump."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/slackdump" if name == "slackdump" else None)


def _create_search_db(db_path: str, messages: list[dict]) -> None:
    """Create a minimal slackdump SQLite database with SEARCH_MESSAGE data."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE SEARCH_MESSAGE ("
        "ID INTEGER PRIMARY KEY, CHUNK_ID INTEGER, LOAD_DTTM TEXT, "
        "CHANNEL_ID TEXT, CHANNEL_NAME TEXT, TS TEXT, TXT TEXT, IDX INTEGER, DATA TEXT)"
    )
    for i, msg in enumerate(messages):
        conn.execute(
            "INSERT INTO SEARCH_MESSAGE (ID, CHUNK_ID, LOAD_DTTM, CHANNEL_ID, CHANNEL_NAME, TS, TXT, IDX, DATA) "
            "VALUES (?, 1, '2026-06-01', ?, ?, ?, ?, ?, ?)",
            (
                i + 1,
                msg.get("channel_id", "C123"),
                msg.get("channel_name", "general"),
                msg.get("ts", f"170000000{i}.000{i}00"),
                msg.get("text", "test message"),
                i,
                json.dumps(msg.get("data", {})),
            ),
        )
    conn.commit()
    conn.close()


class TestSlackdumpAvailable:
    def test_available_when_binary_and_auth_exist(self, fake_slackdump_cache, mock_slackdump_binary):
        assert slack_ops._slackdump_available() is True

    def test_not_available_without_binary(self, fake_slackdump_cache, monkeypatch):
        monkeypatch.setattr(slack_ops, "_slackdump_binary", lambda: None)
        assert slack_ops._slackdump_available() is False

    def test_not_available_without_auth(self, tmp_path, monkeypatch, mock_slackdump_binary):
        empty_cache = tmp_path / ".cache" / "slackdump"
        empty_cache.mkdir(parents=True)
        monkeypatch.setattr(slack_ops, "SLACKDUMP_CACHE_DIR", empty_cache)
        assert slack_ops._slackdump_available() is False


class TestVerifyAuth:
    def test_success(self, fake_slackdump_cache, mock_slackdump_binary, monkeypatch):
        monkeypatch.setenv("SLACK_WORKSPACE_URL", "https://redhat-internal.slack.com")
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = slack_ops.verify_auth()
        assert result["ok"] is True
        assert result["team"] == "redhat-internal.slack.com"
        assert result["team_url"] == "https://redhat-internal.slack.com"
        assert result["error"] is None

    def test_missing_binary(self, fake_slackdump_cache, monkeypatch):
        monkeypatch.setattr(slack_ops, "_slackdump_binary", lambda: None)
        result = slack_ops.verify_auth()
        assert result["ok"] is False
        assert "not found" in result["error"]
        assert "install_slackdump" in result["error"]

    def test_missing_auth(self, tmp_path, monkeypatch, mock_slackdump_binary):
        empty_cache = tmp_path / ".cache" / "slackdump"
        empty_cache.mkdir(parents=True)
        monkeypatch.setattr(slack_ops, "SLACKDUMP_CACHE_DIR", empty_cache)
        result = slack_ops.verify_auth()
        assert result["ok"] is False
        assert "auth credentials" in result["error"].lower() or "slackdump login" in result["error"]

    def test_expired_session(self, fake_slackdump_cache, mock_slackdump_binary, monkeypatch):
        monkeypatch.setenv("SLACK_WORKSPACE_URL", "https://redhat-internal.slack.com")
        mock_result = MagicMock(returncode=1, stdout="", stderr="token_revoked")
        with patch("subprocess.run", return_value=mock_result):
            result = slack_ops.verify_auth()
        assert result["ok"] is False
        assert "expired" in result["error"]
        assert "slackdump login" in result["error"]


class TestSearchMessages:
    def test_returns_parsed_results(self, fake_slackdump_cache, mock_slackdump_binary):
        messages = [
            {
                "channel_id": "C123",
                "channel_name": "conforma",
                "ts": "1700000001.000100",
                "text": "hermetic_task.hermetic violation for odh-ogx-core",
                "data": {
                    "permalink": "https://redhat-internal.slack.com/archives/C123/p1700000001000100",
                    "username": "alice",
                    "thread_ts": "1700000000.000000",
                },
            },
        ]

        def fake_run(cmd, **kwargs):
            tmpdir = cmd[cmd.index("-o") + 1]
            _create_search_db(os.path.join(tmpdir, "slackdump.sqlite"), messages)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            results = slack_ops.search_messages("test query")

        assert len(results) == 1
        assert results[0]["channel"] == "conforma"
        assert results[0]["channel_id"] == "C123"
        assert results[0]["permalink"] == "https://redhat-internal.slack.com/archives/C123/p1700000001000100"
        assert results[0]["user"] == "alice"
        assert results[0]["thread_ts"] == "1700000000.000000"
        assert results[0]["text"] == "hermetic_task.hermetic violation for odh-ogx-core"

    def test_groups_by_thread(self, fake_slackdump_cache, mock_slackdump_binary):
        messages = [
            {
                "channel_id": "C123",
                "channel_name": "general",
                "ts": "1700000001.000100",
                "data": {
                    "permalink": "https://test.slack.com/archives/C123/p1",
                    "username": "alice",
                    "thread_ts": "1700000000.000000",
                },
            },
            {
                "channel_id": "C123",
                "channel_name": "general",
                "ts": "1700000002.000200",
                "data": {
                    "permalink": "https://test.slack.com/archives/C123/p2",
                    "username": "bob",
                    "thread_ts": "1700000000.000000",
                },
            },
        ]

        def fake_run(cmd, **kwargs):
            tmpdir = cmd[cmd.index("-o") + 1]
            _create_search_db(os.path.join(tmpdir, "slackdump.sqlite"), messages)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            results = slack_ops.search_messages("test query")

        assert len(results) == 1

    def test_different_threads_kept_separate(self, fake_slackdump_cache, mock_slackdump_binary):
        messages = [
            {
                "channel_id": "C123",
                "channel_name": "general",
                "ts": "1700000001.000100",
                "data": {
                    "permalink": "https://test.slack.com/archives/C123/p1",
                    "username": "alice",
                    "thread_ts": "1700000000.000000",
                },
            },
            {
                "channel_id": "C456",
                "channel_name": "conforma",
                "ts": "1700000003.000300",
                "data": {
                    "permalink": "https://test.slack.com/archives/C456/p3",
                    "username": "bob",
                    "thread_ts": "1700000003.000300",
                },
            },
        ]

        def fake_run(cmd, **kwargs):
            tmpdir = cmd[cmd.index("-o") + 1]
            _create_search_db(os.path.join(tmpdir, "slackdump.sqlite"), messages)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            results = slack_ops.search_messages("test query")

        assert len(results) == 2

    def test_empty_results(self, fake_slackdump_cache, mock_slackdump_binary):
        def fake_run(cmd, **kwargs):
            tmpdir = cmd[cmd.index("-o") + 1]
            _create_search_db(os.path.join(tmpdir, "slackdump.sqlite"), [])
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            results = slack_ops.search_messages("no-match-query")

        assert results == []

    def test_not_available_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        empty_cache = tmp_path / ".cache" / "slackdump"
        empty_cache.mkdir(parents=True)
        monkeypatch.setattr(slack_ops, "SLACKDUMP_CACHE_DIR", empty_cache)
        results = slack_ops.search_messages("test")
        assert results == []

    def test_date_filter_in_command(self, fake_slackdump_cache, mock_slackdump_binary):
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            tmpdir = cmd[cmd.index("-o") + 1]
            _create_search_db(os.path.join(tmpdir, "slackdump.sqlite"), [])
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            slack_ops.search_messages("test", after_days=30)

        query_arg = captured_cmd[-1]
        assert "after:" in query_arg
        assert "test" in query_arg

    def test_respects_count_limit(self, fake_slackdump_cache, mock_slackdump_binary):
        messages = [
            {
                "channel_id": f"C{i}",
                "channel_name": f"channel-{i}",
                "ts": f"170000000{i}.000{i}00",
                "data": {
                    "permalink": f"https://test.slack.com/archives/C{i}/p{i}",
                    "username": f"user{i}",
                    "thread_ts": f"170000000{i}.000{i}00",
                },
            }
            for i in range(10)
        ]

        def fake_run(cmd, **kwargs):
            tmpdir = cmd[cmd.index("-o") + 1]
            _create_search_db(os.path.join(tmpdir, "slackdump.sqlite"), messages)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            results = slack_ops.search_messages("test", count=3)

        assert len(results) == 3

    def test_expired_session_returns_empty(self, fake_slackdump_cache, mock_slackdump_binary):
        mock_result = MagicMock(returncode=1, stdout="", stderr="token_revoked")
        with patch("subprocess.run", return_value=mock_result):
            results = slack_ops.search_messages("test")
        assert results == []
