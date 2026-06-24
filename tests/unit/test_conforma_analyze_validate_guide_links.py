"""Tests for conforma-analyze validate_guide_links.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as requests_lib

import validate_guide_links as mod


# ---------------------------------------------------------------------------
# Link extraction tests
# ---------------------------------------------------------------------------

class TestExtractMarkdownLinks:
    def test_extracts_standard_links(self):
        content = "See [docs](https://example.com/docs) and [guide](https://example.com/guide)."
        links = mod.extract_markdown_links(content)
        assert links == [
            ("docs", "https://example.com/docs"),
            ("guide", "https://example.com/guide"),
        ]

    def test_deduplicates_urls(self):
        content = "[a](https://example.com) and [b](https://example.com)"
        links = mod.extract_markdown_links(content)
        assert len(links) == 1
        assert links[0][1] == "https://example.com"

    def test_ignores_image_links(self):
        content = "![alt](https://example.com/image.png) but [link](https://example.com)"
        links = mod.extract_markdown_links(content)
        assert len(links) == 1
        assert links[0][0] == "link"

    def test_extracts_anchor_links(self):
        content = "See [`rule`](#violation-hermetic_task-hermetic) for details."
        links = mod.extract_markdown_links(content)
        assert links == [("`rule`", "#violation-hermetic_task-hermetic")]

    def test_empty_content(self):
        assert mod.extract_markdown_links("") == []

    def test_no_links(self):
        assert mod.extract_markdown_links("Just plain text.") == []

    def test_mixed_link_types(self):
        content = (
            "[github](https://github.com/org/repo) "
            "[anchor](#summary) "
            "[gitlab](https://gitlab.example.com/merge_requests/1)"
        )
        links = mod.extract_markdown_links(content)
        assert len(links) == 3

    def test_extracts_html_a_href_links(self):
        content = '<a href="https://example.com/page" target="_blank">page</a>'
        links = mod.extract_markdown_links(content)
        assert len(links) == 1
        assert links[0] == ("page", "https://example.com/page")

    def test_deduplicates_across_markdown_and_html(self):
        content = (
            "[link](https://example.com) and "
            '<a href="https://example.com" target="_blank">link</a>'
        )
        links = mod.extract_markdown_links(content)
        assert len(links) == 1

    def test_extracts_both_markdown_and_html_links(self):
        content = (
            "[md](https://md.example.com) "
            '<a href="https://html.example.com" target="_blank">html</a>'
        )
        links = mod.extract_markdown_links(content)
        assert len(links) == 2
        urls = {u for _, u in links}
        assert "https://md.example.com" in urls
        assert "https://html.example.com" in urls


# ---------------------------------------------------------------------------
# Anchor collection tests
# ---------------------------------------------------------------------------

class TestCollectDocumentAnchors:
    def test_collects_html_anchor_ids(self):
        content = '<a id="violation-hermetic_task-hermetic"></a>'
        anchors = mod._collect_document_anchors(content)
        assert "violation-hermetic_task-hermetic" in anchors

    def test_collects_heading_anchors(self):
        content = "## Executive Summary\n\nSome text.\n\n### Resolution Guide"
        anchors = mod._collect_document_anchors(content)
        assert "executive-summary" in anchors
        assert "resolution-guide" in anchors

    def test_strips_inline_code_from_headings(self):
        content = "### 1. `hermetic_task.hermetic` — 5 components"
        anchors = mod._collect_document_anchors(content)
        assert "1-hermetictaskhermetic-5-components" in anchors

    def test_strips_links_from_headings(self):
        content = "## [Source CSV](https://example.com) Report"
        anchors = mod._collect_document_anchors(content)
        assert "source-csv-report" in anchors

    def test_empty_content(self):
        assert mod._collect_document_anchors("") == set()


# ---------------------------------------------------------------------------
# Auth header routing tests
# ---------------------------------------------------------------------------

class TestAuthHeadersForUrl:
    def test_github_url_gets_github_token(self):
        with patch.object(mod, "_get_github_token", return_value="gh-tok"):
            headers = mod._auth_headers_for_url("https://github.com/org/repo")
        assert headers == {"Authorization": "token gh-tok"}

    def test_gitlab_url_gets_gitlab_token(self):
        with patch.object(mod, "_get_gitlab_token", return_value="gl-tok"):
            headers = mod._auth_headers_for_url("https://gitlab.cee.redhat.com/project")
        assert headers == {"PRIVATE-TOKEN": "gl-tok"}

    def test_unknown_host_gets_no_auth(self):
        headers = mod._auth_headers_for_url("https://example.com/page")
        assert headers == {}

    def test_no_github_token_returns_empty(self):
        with patch.object(mod, "_get_github_token", return_value=""):
            headers = mod._auth_headers_for_url("https://github.com/org/repo")
        assert headers == {}


# ---------------------------------------------------------------------------
# Single link check tests
# ---------------------------------------------------------------------------

class TestCheckSingleLink:
    def test_head_200_ok(self):
        resp = MagicMock(status_code=200)
        with patch.object(mod.requests, "head", return_value=resp):
            result = mod._check_single_link("https://example.com")
        assert result.ok is True
        assert result.status_code == 200

    def test_head_404_broken(self):
        resp = MagicMock(status_code=404)
        with patch.object(mod.requests, "head", return_value=resp):
            result = mod._check_single_link("https://example.com/missing")
        assert result.ok is False
        assert result.status_code == 404

    def test_head_405_falls_back_to_get(self):
        head_resp = MagicMock(status_code=405)
        get_resp = MagicMock(status_code=200)
        with (
            patch.object(mod.requests, "head", return_value=head_resp),
            patch.object(mod.requests, "get", return_value=get_resp),
        ):
            result = mod._check_single_link("https://example.com")
        assert result.ok is True

    def test_connection_error(self):
        with patch.object(mod.requests, "head", side_effect=requests_lib.ConnectionError):
            result = mod._check_single_link("https://unreachable.invalid")
        assert result.ok is False
        assert result.reason == "Connection failed"

    def test_timeout(self):
        with patch.object(mod.requests, "head", side_effect=requests_lib.Timeout):
            result = mod._check_single_link("https://slow.example.com")
        assert result.ok is False
        assert result.reason == "Timeout"


# ---------------------------------------------------------------------------
# Full guide validation tests
# ---------------------------------------------------------------------------

class TestValidateGuideLinks:
    def test_all_links_valid(self):
        content = (
            '## Summary <a id="summary"></a>\n\n'
            "[section](#summary)\n"
            "[example](https://example.com)\n"
        )
        resp = MagicMock(status_code=200)
        with patch.object(mod.requests, "head", return_value=resp):
            report = mod.validate_guide_links(content)
        assert report["all_ok"] is True
        assert report["total"] == 2
        assert report["external_checked"] == 1
        assert report["anchor_checked"] == 1
        assert report["broken"] == []

    def test_broken_anchor(self):
        content = "[missing](#nonexistent-anchor)\n"
        report = mod.validate_guide_links(content)
        assert report["all_ok"] is False
        assert len(report["broken"]) == 1
        assert report["broken"][0]["url"] == "#nonexistent-anchor"
        assert "Anchor target not found" in report["broken"][0]["reason"]

    def test_broken_external_link(self):
        content = "[broken](https://example.com/404)\n"
        resp = MagicMock(status_code=404)
        with patch.object(mod.requests, "head", return_value=resp):
            report = mod.validate_guide_links(content)
        assert report["all_ok"] is False
        assert len(report["broken"]) == 1
        assert report["broken"][0]["status_code"] == 404

    def test_no_links_is_ok(self):
        report = mod.validate_guide_links("Just text, no links.")
        assert report["all_ok"] is True
        assert report["total"] == 0

    def test_mixed_broken_and_valid(self):
        content = (
            '## Heading <a id="exists"></a>\n\n'
            "[ok](#exists)\n"
            "[bad](#missing)\n"
            "[github](https://github.com/org/repo)\n"
            "[dead](https://example.com/gone)\n"
        )
        ok_resp = MagicMock(status_code=200)
        not_found_resp = MagicMock(status_code=404)

        def mock_head(url, **kwargs):
            if "gone" in url:
                return not_found_resp
            return ok_resp

        with patch.object(mod.requests, "head", side_effect=mock_head):
            report = mod.validate_guide_links(content)

        assert report["all_ok"] is False
        assert len(report["broken"]) == 2
        urls = {b["url"] for b in report["broken"]}
        assert "#missing" in urls
        assert "https://example.com/gone" in urls


# ---------------------------------------------------------------------------
# find_latest_guide tests
# ---------------------------------------------------------------------------

class TestFindLatestGuide:
    def test_finds_latest_by_mtime(self, tmp_path):
        old_dir = tmp_path / "20260601-100000"
        old_dir.mkdir()
        old_guide = old_dir / "conforma-resolution-guide.md"
        old_guide.write_text("old", encoding="utf-8")

        new_dir = tmp_path / "20260602-100000"
        new_dir.mkdir()
        new_guide = new_dir / "conforma-resolution-guide.md"
        new_guide.write_text("new", encoding="utf-8")

        result = mod.find_latest_guide(str(tmp_path))
        assert result is not None
        assert "20260602" in result

    def test_returns_none_when_empty(self, tmp_path):
        assert mod.find_latest_guide(str(tmp_path)) is None

    def test_returns_none_for_missing_dir(self):
        assert mod.find_latest_guide("/nonexistent/path") is None
