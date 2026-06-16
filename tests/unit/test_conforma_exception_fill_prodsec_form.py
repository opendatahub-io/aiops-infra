"""Tests for conforma-exception fill_prodsec_form.py (discover + generate + health check)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import fill_prodsec_form as fpf

# ---------------------------------------------------------------------------
# Fixtures: synthetic Google Forms HTML
# ---------------------------------------------------------------------------

_SAMPLE_FB_DATA = [
    None,
    [
        None,
        [
            # Field group 1: short text, required
            [
                None,
                "What is the Conforma policy rule?",
                None,
                None,
                [
                    [
                        1234567890,
                        None,
                        None,
                        0,  # short_text
                        [[None, None, 1]],  # required=True
                    ]
                ],
            ],
            # Field group 2: paragraph, optional
            [
                None,
                "Describe the scope of this exception",
                None,
                None,
                [
                    [
                        9876543210,
                        None,
                        None,
                        1,  # paragraph
                        [[None, None, 0]],  # required=False
                    ]
                ],
            ],
            # Field group 3: radio with options, required
            [
                None,
                "Risk level",
                None,
                None,
                [
                    [
                        5555555555,
                        [["Low"], ["Medium"], ["High"], ["Critical"]],
                        None,
                        2,  # radio
                        [[None, None, 1]],  # required=True
                    ]
                ],
            ],
            # Field group 4: dropdown, optional
            [
                None,
                "Product version",
                None,
                None,
                [
                    [
                        4444444444,
                        [["rhoai-3.3"], ["rhoai-3.4"], ["rhoai-3.5"]],
                        None,
                        3,  # dropdown
                        [[None, None, 0]],  # required=False
                    ]
                ],
            ],
        ],
    ],
    None,
    "ProdSec Exception Request Form",
]


def _build_html(fb_data: list | None = None) -> str:
    """Build a minimal Google Forms HTML page with embedded FB_PUBLIC_LOAD_DATA_."""
    data = json.dumps(fb_data or _SAMPLE_FB_DATA)
    return f"<html><script>FB_PUBLIC_LOAD_DATA_ = {data};</script></html>"


@pytest.fixture
def sample_html(tmp_path) -> Path:
    p = tmp_path / "form.html"
    p.write_text(_build_html())
    return p


@pytest.fixture
def sample_config(tmp_path) -> Path:
    """A config YAML with form_url and mapped fields."""
    config = {
        "form_title": "ProdSec Exception Request Form",
        "discovered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "field_count": 4,
        "form_url": "https://docs.google.com/forms/d/e/FAKE_ID/viewform",
        "fields": [
            {"entry_id": "1234567890", "question": "Conforma policy rule?", "field_type": "short_text", "required": True},
            {"entry_id": "9876543210", "question": "Scope", "field_type": "paragraph", "required": False},
            {"entry_id": "5555555555", "question": "Risk level", "field_type": "radio", "required": True,
             "options": ["Low", "Medium", "High", "Critical"]},
            {"entry_id": "4444444444", "question": "Product version", "field_type": "dropdown", "required": False,
             "options": ["rhoai-3.3", "rhoai-3.4", "rhoai-3.5"]},
        ],
        "field_mapping": {
            "entry_1234567890": "rule",
            "entry_9876543210": "exception_scope",
            "entry_5555555555": "exception_risk",
            "entry_4444444444": "rhoai_version",
        },
    }
    p = tmp_path / "prodsec_form_config.yaml"
    with open(p, "w") as fh:
        yaml.dump(config, fh)
    return p


# ---------------------------------------------------------------------------
# Discover mode tests
# ---------------------------------------------------------------------------

class TestExtractFbData:
    def test_extracts_valid_fb_data(self):
        html = _build_html()
        result = fpf._extract_fb_data(html)
        assert isinstance(result, list)
        assert result[3] == "ProdSec Exception Request Form"

    def test_raises_on_missing_fb_data(self):
        with pytest.raises(ValueError, match="Could not find FB_PUBLIC_LOAD_DATA_"):
            fpf._extract_fb_data("<html><body>No form here</body></html>")

    def test_handles_multiline_fb_data(self):
        data = json.dumps(_SAMPLE_FB_DATA, indent=2)
        html = f"<html><script>\nFB_PUBLIC_LOAD_DATA_ = {data}\n;</script></html>"
        result = fpf._extract_fb_data(html)
        assert result[3] == "ProdSec Exception Request Form"


class TestParseFormFields:
    def test_parses_all_fields(self):
        title, fields = fpf._parse_form_fields(_SAMPLE_FB_DATA)
        assert title == "ProdSec Exception Request Form"
        assert len(fields) == 4

    def test_field_types_identified(self):
        _, fields = fpf._parse_form_fields(_SAMPLE_FB_DATA)
        types = {f["entry_id"]: f["field_type"] for f in fields}
        assert types["1234567890"] == "short_text"
        assert types["9876543210"] == "paragraph"
        assert types["5555555555"] == "radio"
        assert types["4444444444"] == "dropdown"

    def test_required_flags(self):
        _, fields = fpf._parse_form_fields(_SAMPLE_FB_DATA)
        required = {f["entry_id"]: f["required"] for f in fields}
        assert required["1234567890"] is True
        assert required["9876543210"] is False
        assert required["5555555555"] is True

    def test_options_extracted(self):
        _, fields = fpf._parse_form_fields(_SAMPLE_FB_DATA)
        radio_field = next(f for f in fields if f["entry_id"] == "5555555555")
        assert radio_field["options"] == ["Low", "Medium", "High", "Critical"]

    def test_text_fields_have_no_options(self):
        _, fields = fpf._parse_form_fields(_SAMPLE_FB_DATA)
        text_field = next(f for f in fields if f["entry_id"] == "1234567890")
        assert text_field["options"] is None


class TestDiscover:
    def test_returns_config_dict(self, sample_html):
        config = fpf.discover(sample_html)
        assert config["form_title"] == "ProdSec Exception Request Form"
        assert config["field_count"] == 4
        assert len(config["fields"]) == 4
        assert len(config["field_mapping"]) == 4

    def test_field_mapping_keys_match_entry_ids(self, sample_html):
        config = fpf.discover(sample_html)
        entry_ids = {f["entry_id"] for f in config["fields"]}
        mapping_ids = {k.replace("entry_", "") for k in config["field_mapping"]}
        assert entry_ids == mapping_ids

    def test_all_mappings_initially_none(self, sample_html):
        config = fpf.discover(sample_html)
        assert all(v is None for v in config["field_mapping"].values())


class TestWriteConfig:
    def test_writes_yaml(self, sample_html, tmp_path):
        config = fpf.discover(sample_html)
        output = tmp_path / "output.yaml"
        fpf.write_config(config, output)
        assert output.is_file()

        loaded = yaml.safe_load(output.read_text())
        assert loaded["form_title"] == "ProdSec Exception Request Form"
        assert len(loaded["fields"]) == 4


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------

class TestValidateConfig:
    def test_healthy_config(self, sample_config):
        warnings = fpf.validate_config(sample_config)
        assert len(warnings) == 0

    def test_missing_file_returns_error(self, tmp_path):
        warnings = fpf.validate_config(tmp_path / "nonexistent.yaml")
        assert len(warnings) == 1
        assert warnings[0].level == "error"
        assert "not found" in warnings[0].message

    def test_stale_config_warns(self, tmp_path):
        config = {
            "form_title": "Test",
            "discovered_at": "2024-01-01T00:00:00+00:00",
            "field_count": 1,
            "fields": [{"entry_id": "123", "question": "Q", "field_type": "short_text", "required": False}],
            "field_mapping": {"entry_123": "rule"},
        }
        p = tmp_path / "stale.yaml"
        with open(p, "w") as fh:
            yaml.dump(config, fh)

        warnings = fpf.validate_config(p)
        staleness_warnings = [w for w in warnings if "days old" in w.message]
        assert len(staleness_warnings) == 1
        assert staleness_warnings[0].level == "warn"

    def test_empty_mapping_returns_error(self, tmp_path):
        config = {
            "form_title": "Test",
            "discovered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "field_count": 1,
            "fields": [{"entry_id": "123", "question": "Q", "field_type": "short_text", "required": True}],
            "field_mapping": {"entry_123": None},
        }
        p = tmp_path / "empty_mapping.yaml"
        with open(p, "w") as fh:
            yaml.dump(config, fh)

        warnings = fpf.validate_config(p)
        errors = [w for w in warnings if w.level == "error"]
        assert any("No fields are mapped" in w.message for w in errors)

    def test_unmapped_required_field_warns(self, tmp_path):
        config = {
            "form_title": "Test",
            "discovered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "field_count": 2,
            "fields": [
                {"entry_id": "111", "question": "Mapped", "field_type": "short_text", "required": False},
                {"entry_id": "222", "question": "Required but unmapped", "field_type": "short_text", "required": True},
            ],
            "field_mapping": {"entry_111": "rule", "entry_222": None},
        }
        p = tmp_path / "unmapped_required.yaml"
        with open(p, "w") as fh:
            yaml.dump(config, fh)

        warnings = fpf.validate_config(p)
        req_warnings = [w for w in warnings if "Required form fields not mapped" in w.message]
        assert len(req_warnings) == 1


# ---------------------------------------------------------------------------
# Generate mode tests
# ---------------------------------------------------------------------------

class TestGeneratePrefillUrl:
    def test_basic_url_generation(self, sample_config):
        url = fpf.generate_prefill_url(
            config_path=sample_config,
            rule="hermetic_task.hermetic",
            exception_scope="Non-hermetic build",
        )
        assert "entry.1234567890=hermetic_task.hermetic" in url
        assert "entry.9876543210=Non-hermetic%20build" in url

    def test_radio_field_matches_option(self, sample_config):
        url = fpf.generate_prefill_url(
            config_path=sample_config,
            rule="test.rule",
            exception_risk="low",  # should match "Low" option
        )
        assert "entry.5555555555=Low" in url

    def test_dropdown_field_matches_option(self, sample_config):
        url = fpf.generate_prefill_url(
            config_path=sample_config,
            rhoai_version="rhoai-3.4",
        )
        assert "entry.4444444444=rhoai-3.4" in url

    def test_empty_values_skipped(self, sample_config):
        url = fpf.generate_prefill_url(
            config_path=sample_config,
            rule="test.rule",
        )
        assert "entry.9876543210" not in url
        assert "entry.1234567890=test.rule" in url

    def test_all_empty_returns_base_url(self, sample_config):
        url = fpf.generate_prefill_url(config_path=sample_config)
        assert url == "https://docs.google.com/forms/d/e/FAKE_ID/viewform"
        assert "entry." not in url

    def test_form_id_fallback(self, tmp_path):
        config = {
            "form_title": "Test",
            "form_id": "1FAIpQLSdTest",
            "discovered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "field_count": 1,
            "fields": [{"entry_id": "123", "question": "Q", "field_type": "short_text", "required": False}],
            "field_mapping": {"entry_123": "rule"},
        }
        p = tmp_path / "formid.yaml"
        with open(p, "w") as fh:
            yaml.dump(config, fh)

        url = fpf.generate_prefill_url(config_path=p, rule="test.rule")
        assert url.startswith("https://docs.google.com/forms/d/e/1FAIpQLSdTest/viewform")
        assert "entry.123=test.rule" in url

    def test_missing_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            fpf.generate_prefill_url(config_path=tmp_path / "missing.yaml")

    def test_no_form_url_or_id_raises(self, tmp_path):
        config = {
            "form_title": "Test",
            "discovered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "field_count": 1,
            "fields": [{"entry_id": "123", "question": "Q", "field_type": "short_text", "required": False}],
            "field_mapping": {"entry_123": "rule"},
        }
        p = tmp_path / "noid.yaml"
        with open(p, "w") as fh:
            yaml.dump(config, fh)

        with pytest.raises(ValueError, match="form_url.*form_id"):
            fpf.generate_prefill_url(config_path=p, rule="test")


class TestMatchOption:
    def test_exact_match(self):
        assert fpf._match_option("Low", ["Low", "Medium", "High"]) == "Low"

    def test_case_insensitive(self):
        assert fpf._match_option("low", ["Low", "Medium", "High"]) == "Low"

    def test_partial_match(self):
        assert fpf._match_option("rhoai-3.4", ["rhoai-3.3", "rhoai-3.4", "rhoai-3.5"]) == "rhoai-3.4"

    def test_no_match_returns_none(self):
        assert fpf._match_option("unknown", ["Low", "Medium", "High"]) is None

    def test_substring_match(self):
        assert fpf._match_option("Medium risk", ["Low", "Medium", "High"]) == "Medium"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCli:
    def test_discover_writes_config(self, sample_html, tmp_path):
        output = tmp_path / "cli_output.yaml"
        rc = fpf.main(["--discover", str(sample_html), "--output", str(output)])
        assert rc == 0
        assert output.is_file()

    def test_discover_missing_file(self):
        rc = fpf.main(["--discover", "/nonexistent/form.html"])
        assert rc == 1

    def test_validate_healthy(self, sample_config):
        rc = fpf.main(["--validate-config", "--config", str(sample_config)])
        assert rc == 0

    def test_validate_missing_config(self, tmp_path):
        rc = fpf.main(["--validate-config", "--config", str(tmp_path / "missing.yaml")])
        assert rc == 1

    def test_generate_prints_url(self, sample_config, capsys):
        rc = fpf.main([
            "--generate",
            "--config", str(sample_config),
            "--rule", "test.rule",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        assert "entry.1234567890=test.rule" in captured.out

    def test_generate_with_missing_config_fails(self, tmp_path):
        rc = fpf.main([
            "--generate",
            "--config", str(tmp_path / "missing.yaml"),
            "--rule", "test.rule",
        ])
        assert rc == 1
