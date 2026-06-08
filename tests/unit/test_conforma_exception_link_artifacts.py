"""Tests for conforma-exception link_artifacts.py."""

from __future__ import annotations

from unittest.mock import patch

import link_artifacts as la


class TestBuildProvenanceFooter:
    def test_includes_repo_and_user(self):
        with (
            patch("link_artifacts.getpass.getuser", return_value="testuser"),
            patch("link_artifacts.platform.node", return_value="testhost"),
        ):
            footer = la.build_provenance_footer()
        assert "---" in footer
        assert la.PROVENANCE_REPO in footer
        assert "conforma-exception" in footer
        assert "testuser@testhost" in footer


class TestAddRemoteLinkDryRun:
    def test_dry_run_returns_status_without_api_call(self):
        result = la.add_remote_link(
            "RHOAIENG-123",
            "https://gitlab.example.com/mr/1",
            "Test MR",
            dry_run=True,
        )
        assert result == {
            "status": "dry_run",
            "ticket_key": "RHOAIENG-123",
            "remote_link": "https://gitlab.example.com/mr/1",
        }


class TestAddLabelDryRun:
    def test_dry_run_returns_required_labels(self):
        result = la.add_label("PSX-456", dry_run=True)
        assert result == {
            "status": "dry_run",
            "ticket_key": "PSX-456",
            "labels": [la.PROVENANCE_LABEL, la.VIOLATION_LABEL],
        }


class TestCommentOnTicketDryRun:
    def test_dry_run_includes_mr_url_and_provenance(self):
        mr_url = "https://gitlab.example.com/mr/99"
        with (
            patch("link_artifacts.getpass.getuser", return_value="user"),
            patch("link_artifacts.platform.node", return_value="host"),
        ):
            result = la.comment_on_ticket("RHOAIENG-789", mr_url, dry_run=True)
        assert result["status"] == "dry_run"
        assert result["ticket_key"] == "RHOAIENG-789"
        assert mr_url in result["comment"]
        assert la.PROVENANCE_REPO in result["comment"]


class TestEnsureLinkDryRun:
    def test_dry_run_returns_link_details(self):
        result = la.ensure_link("RHOAIENG-100", "PSX-200", link_type="Blocks", dry_run=True)
        assert result == {
            "status": "dry_run",
            "from": "RHOAIENG-100",
            "to": "PSX-200",
            "link_type": "Blocks",
        }


class TestLinkAllDryRun:
    def test_link_all_orchestrates_all_steps(self):
        mr_url = "https://gitlab.cee.redhat.com/releng/konflux-release-data/-/merge_requests/18281"
        rhoaieng_url = "https://redhat.atlassian.net/browse/RHOAIENG-62569"
        psx_url = "https://redhat.atlassian.net/browse/PSX-1042"

        result = la.link_all(
            mr_url=mr_url,
            rhoaieng_url=rhoaieng_url,
            psx_url=psx_url,
            link_to="RHAISTRAT-576",
            related_psx="PSX-999",
            mr_title="Exception MR rhoai-3.3",
            dry_run=True,
        )

        assert result["status"] == "completed"
        assert result["failures"] == []
        assert result["warnings"] == []

        statuses = [r["status"] for r in result["results"]]
        # Two tickets × (remote link + comment + label) = 6, plus 5 ensure_link calls
        assert statuses.count("dry_run") == 11
        assert len(result["results"]) == 11

        dry_run_results = [r for r in result["results"] if r["status"] == "dry_run"]
        remote_links = [r for r in dry_run_results if "remote_link" in r]
        assert len(remote_links) == 2
        assert all(r["remote_link"] == mr_url for r in remote_links)

        link_ops = [r for r in dry_run_results if "link_type" in r]
        assert any(
            r["from"] == "RHOAIENG-62569" and r["to"] == "PSX-1042" and r["link_type"] == "Blocks" for r in link_ops
        )
        assert any(r["from"] == "RHOAIENG-62569" and r["to"] == "RHAISTRAT-576" for r in link_ops)
        assert any(r["from"] == "PSX-1042" and r["to"] == "PSX-999" for r in link_ops)
