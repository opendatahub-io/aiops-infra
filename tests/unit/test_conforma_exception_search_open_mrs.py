"""Tests for conforma-exception search_open_mrs.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILL_SCRIPTS = _REPO_ROOT / "skills/conforma-exception/scripts"

# Stub heavy transitive deps before loading the module under test.
_stubs = {}
for _mod_name in ("preflight_check", "gitlab_ops", "cli_runner", "_setup_env"):
    if _mod_name not in sys.modules:
        _stubs[_mod_name] = MagicMock()
        sys.modules[_mod_name] = _stubs[_mod_name]

_spec = importlib.util.spec_from_file_location(
    "search_open_mrs_under_test",
    _SKILL_SCRIPTS / "search_open_mrs.py",
)
search_open_mrs = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(search_open_mrs)

for _mod_name in list(_stubs):
    del sys.modules[_mod_name]


# -- Fixtures ----------------------------------------------------------------

_MR_AMD = {
    "iid": 18625,
    "title": (
        "[AMD] [RHOAI] Conforma exception: "
        "rpm_signature.allowed:9386b48a1a693c5c "
        "for rhoai-2.25, rhoai-3.3, rhoai-3.4, rhoai-3.5-ea.1"
    ),
    "web_url": "https://gitlab.example.com/-/merge_requests/18625",
    "author": {"username": "alice"},
    "created_at": "2026-06-03T10:00:00Z",
    "labels": ["tenant/rhoai"],
    "source_branch": "conforma-exception/rpm_sig",
    "target_branch": "main",
}

_MR_INTEL = {
    "iid": 18628,
    "title": (
        "[Intel] [RHOAI] Conforma exception: "
        "rpm_signature.allowed:28da432daac8baea "
        "for rhoai-2.25, rhoai-3.3, rhoai-3.4"
    ),
    "web_url": "https://gitlab.example.com/-/merge_requests/18628",
    "author": "bob",  # python-gitlab path returns a plain string
    "created_at": "",
    "labels": [],
    "source_branch": "conforma-exception/rpm_sig_intel",
    "target_branch": "main",
}

_MR_HERMETIC = {
    "iid": 18362,
    "title": "RHAIENG-3467: Extend hermetic_task.hermetic for rhoai-2.25, 3.3, 3.4",
    "web_url": "https://gitlab.example.com/-/merge_requests/18362",
    "author": {"username": "carol"},
    "created_at": "2026-05-28T09:00:00Z",
    "labels": [],
    "source_branch": "hermetic-extend",
    "target_branch": "main",
}


# -- _normalize_author -------------------------------------------------------


class TestNormalizeAuthor:
    def test_dict_author(self):
        assert search_open_mrs._normalize_author({"username": "alice"}) == "alice"

    def test_string_author(self):
        assert search_open_mrs._normalize_author("bob") == "bob"

    def test_empty_dict(self):
        assert search_open_mrs._normalize_author({}) == ""

    def test_none(self):
        assert search_open_mrs._normalize_author(None) == ""


# -- _normalize_mr -----------------------------------------------------------


class TestNormalizeMr:
    def test_raw_api_format(self):
        result = search_open_mrs._normalize_mr(_MR_AMD)
        assert result["iid"] == 18625
        assert result["author"] == "alice"
        assert result["url"] == _MR_AMD["web_url"]
        assert result["labels"] == ["tenant/rhoai"]

    def test_python_gitlab_format(self):
        result = search_open_mrs._normalize_mr(_MR_INTEL)
        assert result["author"] == "bob"
        assert result["created_at"] == ""


# -- _parse_title ------------------------------------------------------------


class TestParseTitle:
    def test_standard_title(self):
        parsed = search_open_mrs._parse_title(_MR_AMD["title"])
        assert parsed["vendor"] == "AMD"
        assert parsed["rule"] == "rpm_signature.allowed:9386b48a1a693c5c"
        assert parsed["versions"] == [
            "rhoai-2.25",
            "rhoai-3.3",
            "rhoai-3.4",
            "rhoai-3.5-ea.1",
        ]

    def test_non_standard_title(self):
        parsed = search_open_mrs._parse_title(_MR_HERMETIC["title"])
        assert parsed == {}


# -- search (with mocked _glab_get_mrs) -------------------------------------


class TestSearch:
    def _patch_glab(self, mrs_by_term: dict[str, list[dict]]):
        def fake_glab(term):
            return mrs_by_term.get(term, [])

        return patch.object(search_open_mrs, "_glab_get_mrs", side_effect=fake_glab)

    def test_broad_search(self):
        with self._patch_glab({"Conforma exception": [_MR_AMD, _MR_INTEL]}):
            results = search_open_mrs.search()
        assert len(results) == 2

    def test_filter_by_version(self):
        with self._patch_glab({"Conforma exception": [_MR_AMD, _MR_INTEL]}):
            results = search_open_mrs.search(version="rhoai-3.5-ea.1")
        assert len(results) == 1
        assert results[0]["iid"] == 18625

    def test_filter_by_version_short_form(self):
        with self._patch_glab({"Conforma exception": [_MR_AMD, _MR_INTEL]}):
            results = search_open_mrs.search(version="3.4")
        assert len(results) == 2

    def test_filter_by_author(self):
        with self._patch_glab({"Conforma exception": [_MR_AMD, _MR_INTEL]}):
            results = search_open_mrs.search(author="alice")
        assert len(results) == 1
        assert results[0]["iid"] == 18625

    def test_rule_search_deduplicates(self):
        with self._patch_glab(
            {
                "rpm_signature.allowed:9386b48a": [_MR_AMD],
                "9386b48a": [_MR_AMD],  # duplicate via suffix search
                "rpm_signature": [_MR_AMD, _MR_INTEL],
            }
        ):
            results = search_open_mrs.search(rule="rpm_signature.allowed:9386b48a")
        iids = [mr["iid"] for mr in results]
        assert len(iids) == len(set(iids)), "duplicates not removed"

    def test_rule_search_prefix_expansion(self):
        with self._patch_glab(
            {
                "hermetic_task": [_MR_HERMETIC],
            }
        ):
            results = search_open_mrs.search(rule="hermetic_task")
        assert len(results) == 1
        assert results[0]["iid"] == 18362


# -- format_text / format_markdown -------------------------------------------


class TestFormatText:
    def test_no_results(self):
        output = search_open_mrs.format_text([], "rpm_signature", None, None)
        assert "No open conforma exception MRs found" in output
        assert "rpm_signature" in output

    def test_with_results(self):
        mrs = [search_open_mrs._normalize_mr(_MR_AMD)]
        mrs[0]["parsed"] = search_open_mrs._parse_title(mrs[0]["title"])
        output = search_open_mrs.format_text(mrs, None, None, None)
        assert "!18625" in output
        assert "AMD" in output


class TestFormatMarkdown:
    def test_no_results(self):
        output = search_open_mrs.format_markdown([])
        assert "No open conforma exception MRs found" in output

    def test_table_header(self):
        mrs = [search_open_mrs._normalize_mr(_MR_AMD)]
        mrs[0]["parsed"] = search_open_mrs._parse_title(mrs[0]["title"])
        output = search_open_mrs.format_markdown(mrs)
        assert "| MR |" in output
        assert "!18625" in output
