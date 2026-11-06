"""Tests for safe, idempotent GAP component/image map updates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import component_repo_map as mapping  # noqa: E402


def _details(**overrides) -> dict:
    inputs = {
        "product_context": "RHOAI",
        "component_name": "odh-eval-hub",
        "repo_url": "https://github.com/red-hat-data-services/eval-hub.git",
        "release_category": "Generally Available",
    }
    inputs.update(overrides)
    return {"inputs": inputs}


class TestExpectedEntries:
    def test_primary_component_uses_source_and_delivery_repo_names(self):
        repo, entries = mapping.expected_entries(_details())
        assert repo == "eval-hub"
        assert entries == {"odh-eval-hub": "rhoai/odh-eval-hub-rhel9"}

    @pytest.mark.parametrize(
        ("versioned", "canonical"),
        [
            ("odh-eval-hub-v3-6", "odh-eval-hub"),
            ("odh-eval-hub-v3-6-ea-1", "odh-eval-hub"),
            ("odh-eval-hub-3-6", "odh-eval-hub"),
        ],
    )
    def test_release_suffix_is_removed_from_component_key(self, versioned, canonical):
        assert mapping.canonical_component_name(versioned) == canonical

    def test_beta_uses_actual_beta_delivery_namespace(self):
        _, entries = mapping.expected_entries(_details(release_category="Beta"))
        assert entries["odh-eval-hub"] == "rhoai-beta/odh-eval-hub-rhel9"

    def test_additional_components_support_multi_component_sources(self):
        details = _details(
            component_repo_map=[
                {"component_name": "odh-eval-hub-v3-6", "image_repository": "rhoai/odh-eval-hub-rhel9"},
                {"component_name": "odh-eval-hub-inspectai", "image_repository": "rhoai/odh-eval-hub-inspectai-rhel9"},
            ]
        )
        repo, entries = mapping.expected_entries(details)
        assert repo == "eval-hub"
        assert entries == {
            "odh-eval-hub": "rhoai/odh-eval-hub-rhel9",
            "odh-eval-hub-inspectai": "rhoai/odh-eval-hub-inspectai-rhel9",
        }


class TestMapUpdates:
    def test_adds_multiple_entries_and_preserves_unrelated_mappings(self):
        data = {"unrelated-repo": {"odh-existing": "rhoai/odh-existing-rhel9"}}
        changed = mapping.update_map(
            data,
            "eval-hub",
            {
                "odh-eval-hub": "rhoai/odh-eval-hub-rhel9",
                "odh-eval-hub-inspectai": "rhoai/odh-eval-hub-inspectai-rhel9",
            },
        )
        assert changed
        assert data["unrelated-repo"] == {"odh-existing": "rhoai/odh-existing-rhel9"}
        assert data["eval-hub"]["odh-eval-hub-inspectai"] == "rhoai/odh-eval-hub-inspectai-rhel9"

    def test_correct_existing_mapping_is_noop(self):
        data = {"eval-hub": {"odh-eval-hub": "rhoai/odh-eval-hub-rhel9"}}
        assert not mapping.update_map(data, "eval-hub", {"odh-eval-hub": "rhoai/odh-eval-hub-rhel9"})
        mapping.verify_map(data, "eval-hub", {"odh-eval-hub": "rhoai/odh-eval-hub-rhel9"})

    def test_same_image_versioned_alias_is_canonicalized(self):
        data = {"eval-hub": {"odh-eval-hub-v3-6": "rhoai/odh-eval-hub-rhel9"}}
        assert mapping.update_map(data, "eval-hub", {"odh-eval-hub": "rhoai/odh-eval-hub-rhel9"})
        assert data == {"eval-hub": {"odh-eval-hub": "rhoai/odh-eval-hub-rhel9"}}

    def test_conflicting_mapping_is_not_overwritten(self):
        data = {"eval-hub": {"odh-eval-hub": "rhoai/old-image-rhel9"}}
        before = json.loads(json.dumps(data))
        with pytest.raises(ValueError, match="conflicting mapping"):
            mapping.update_map(data, "eval-hub", {"odh-eval-hub": "rhoai/odh-eval-hub-rhel9"})
        assert data == before

    def test_verify_fails_when_requested_entry_is_missing_or_wrong(self):
        with pytest.raises(ValueError, match="not verified on main"):
            mapping.verify_map({}, "eval-hub", {"odh-eval-hub": "rhoai/odh-eval-hub-rhel9"})

    def test_rejects_malformed_map(self):
        with pytest.raises(ValueError, match="expected an object"):
            mapping.update_map({"eval-hub": []}, "eval-hub", {"odh-eval-hub": "rhoai/x"})


class TestMapRemoval:
    def test_removes_component_but_preserves_other_components_in_repo(self):
        data = {
            "eval-hub": {
                "odh-eval-hub": "rhoai/odh-eval-hub-rhel9",
                "odh-eval-hub-inspectai": "rhoai/odh-eval-hub-inspectai-rhel9",
            },
            "unrelated-repo": {"odh-existing": "rhoai/odh-existing-rhel9"},
        }
        assert mapping.remove_components(data, "eval-hub", {"odh-eval-hub"})
        assert data["eval-hub"] == {
            "odh-eval-hub-inspectai": "rhoai/odh-eval-hub-inspectai-rhel9"
        }
        assert "unrelated-repo" in data

    def test_removes_entire_repository_key_when_last_component_is_deleted(self):
        data = {"eval-hub": {"odh-eval-hub": "rhoai/odh-eval-hub-rhel9"}}
        assert mapping.remove_components(data, "eval-hub", {"odh-eval-hub"})
        assert data == {}

    def test_removes_additional_components_and_numeric_release_aliases(self):
        details = {
            "inputs": {
                "repo_url": "https://github.com/red-hat-data-services/eval-hub",
                "component_name": "odh-eval-hub-v3-6",
                "component_repo_map_components": ["odh-eval-hub-inspectai-v3-6"],
            }
        }
        repo, names = mapping.removal_targets(details)
        data = {
            "eval-hub": {
                "odh-eval-hub-v3-6": "rhoai/odh-eval-hub-rhel9",
                "odh-eval-hub-inspectai-v3-6": "rhoai/odh-eval-hub-inspectai-rhel9",
            }
        }
        assert mapping.remove_components(data, repo, names)
        assert data == {}

    def test_already_absent_is_noop_and_verifies(self):
        data = {"eval-hub": {"odh-other": "rhoai/odh-other-rhel9"}}
        assert not mapping.remove_components(data, "eval-hub", {"odh-eval-hub"})
        mapping.verify_removed(data, "eval-hub", {"odh-eval-hub"})

    def test_verification_rejects_empty_repository_key(self):
        with pytest.raises(ValueError, match="empty repository key"):
            mapping.verify_removed({"eval-hub": {}}, "eval-hub", {"odh-eval-hub"})
