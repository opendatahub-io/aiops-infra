"""Tests for the deterministic C14 Jira project-field mapping."""

import pytest

import conforma_jira_mapping_ops as mod


def test_repository_mapping_is_valid_and_contains_all_discovery_projects():
    mapping = mod.load_project_mapping()
    assert set(mapping["projects"]) == {"RHOAIENG", "RHAIENG", "RHAI", "AIPCC", "OCPEXCEPT", "PSX", "PRODSECRM"}
    assert mapping["projects"]["RHOAIENG"]["target_version_fields"] == ["customfield_10855"]
    assert mapping["projects"]["OCPEXCEPT"]["target_version_fields"] == []


def test_unknown_project_is_not_assumed_to_have_a_version_field():
    with pytest.raises(ValueError, match="No Jira field mapping"):
        mod.project_config("UNKNOWN")
