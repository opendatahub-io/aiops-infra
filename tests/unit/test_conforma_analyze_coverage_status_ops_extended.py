"""Tests for conforma-analyze coverage_status_ops.py — branches missed by the base test file."""

from __future__ import annotations

import json

import pytest

from coverage_status_ops import extract_exception_expiry
from coverage_status_ops import load_report_metadata
from coverage_status_ops import map_gate_status


class TestMapGateStatusLabel:
    def test_partial_status_computes_label(self):
        """Gate status 'partial' → coverage_label is None → computed from counts."""
        coverage, label = map_gate_status(
            {"status": "partial"},
            "rule.x",
            ["comp-a", "comp-b", "comp-c"],
            ["comp-a"],
        )
        assert coverage == "partially_covered"
        assert label == "1 of 3 without exception coverage"

    def test_unknown_status_raises(self):
        with pytest.raises(ValueError, match="Unknown gate status 'weird'"):
            map_gate_status({"status": "weird"}, "rule.x", [], [])

    def test_permanent_label(self):
        coverage, label = map_gate_status({"status": "permanent"}, "rule.x", ["a"], [])
        assert (coverage, label) == ("fully_covered", "permanently excluded")

    def test_blocked_label(self):
        coverage, label = map_gate_status({"status": "blocked"}, "rule.x", ["a"], [])
        assert (coverage, label) == ("fully_covered", "already covered")


class TestExtractExceptionExpiryEdges:
    def test_permanent_status_flag(self):
        result = extract_exception_expiry({"status": "permanent", "permanent_exclusions": []})
        assert result["is_permanent"] is True
        assert result["display_expiry"] == "permanent (no expiry)"

    def test_invalid_date_skipped(self):
        """Invalid effectiveUntil dates are silently skipped."""
        result = extract_exception_expiry(
            {
                "status": "blocked",
                "permanent_exclusions": [],
                "active_exceptions": [
                    {"effectiveUntil": "not-a-date"},
                    {"effectiveUntil": "2027-01-15T00:00:00Z"},
                ],
            }
        )
        assert result["is_permanent"] is False
        assert result["earliest_expiry"] == "2027-01-15"
        assert result["display_expiry"] == "expires 2027-01-15"

    def test_multiple_dates_range(self):
        result = extract_exception_expiry(
            {
                "status": "blocked",
                "permanent_exclusions": [],
                "active_exceptions": [
                    {"effectiveUntil": "2027-03-01"},
                    {"effectiveUntil": "2026-11-01"},
                    {"effectiveUntil": "2027-03-01"},
                ],
            }
        )
        assert result["earliest_expiry"] == "2026-11-01"
        assert result["latest_expiry"] == "2027-03-01"
        assert result["display_expiry"] == "expires 2026-11-01 — 2027-03-01"

    def test_no_dates_empty_display(self):
        result = extract_exception_expiry(
            {
                "status": "blocked",
                "permanent_exclusions": [],
                "active_exceptions": [{"effectiveUntil": None}, {"no_key": 1}],
            }
        )
        assert result["is_permanent"] is False
        assert result["display_expiry"] == ""
        assert result["expiry_dates"] == []


class TestLoadReportMetadataEdges:
    def test_missing_metadata_file(self, tmp_path):
        """Path doesn't exist → returns only the release."""
        meta = load_report_metadata("rhoai-3.4", str(tmp_path / "nope.json"))
        assert meta == {"release": "rhoai-3.4"}

    def test_invalid_json_ignored(self, tmp_path):
        """Malformed JSON → falls back to release-only metadata."""
        bad = tmp_path / "fetch-metadata.json"
        bad.write_text("{not valid json")
        meta = load_report_metadata("rhoai-3.4", str(bad))
        assert meta == {"release": "rhoai-3.4"}

    def test_full_metadata(self, tmp_path):
        meta_file = tmp_path / "fetch-metadata.json"
        meta_file.write_text(
            json.dumps(
                {
                    "releases": {
                        "rhoai-3.4": {
                            "source_path": "reports/rhoai-3.4.csv",
                            "created_at": "2026-01-15T10:00:00Z",
                            "source_sha": "abc123",
                        }
                    }
                }
            )
        )
        meta = load_report_metadata("rhoai-3.4", str(meta_file))
        assert meta["source_path"] == "reports/rhoai-3.4.csv"
        assert meta["created_at"] == "2026-01-15T10:00:00Z"
        assert "abc123" in meta["source_url"]
        assert "/blob/abc123/reports/rhoai-3.4.csv" in meta["source_url"]

    def test_unknown_release(self, tmp_path):
        """Release not present in metadata → only release key."""
        meta_file = tmp_path / "fetch-metadata.json"
        meta_file.write_text(json.dumps({"releases": {"rhoai-3.5": {"source_path": "x"}}}))
        meta = load_report_metadata("rhoai-3.4", str(meta_file))
        assert meta == {"release": "rhoai-3.4"}

    def test_no_metadata_file_arg(self):
        meta = load_report_metadata("rhoai-3.4", None)
        assert meta == {"release": "rhoai-3.4"}

    def test_none_release_unknown(self, tmp_path):
        meta = load_report_metadata(None, None)
        assert meta == {"release": "unknown"}
