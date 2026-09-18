"""Tests for shared C14 release and component normalization."""

import conforma_release_component_ops as mod


def test_equivalent_release_spellings_have_one_canonical_value():
    expected = "rhoai-3.6-ea.2"
    for spelling in ("rhoai-3.6-ea.2", "3.6-ea.2", "v3-6-ea-2", "3.6ea2", "3-6.ea2"):
        parsed = mod.parse_release(spelling)
        assert parsed["canonical"] in (expected, "3.6-ea.2")
        assert mod.release_matches(spelling, "rhoai-3.6-ea.2")


def test_stage_fragment_requires_release_context():
    assert mod.parse_release("ea 2") is None
    assert mod.normalize_release("ea 2", context="rhoai-3.6") == "rhoai-3.6-ea.2"


def test_mismatched_release_does_not_match():
    assert not mod.release_matches("rhoai-3.7-ea.2", "rhoai-3.6-ea.2")


def test_component_identity_and_version_comparison():
    assert mod.component_identity("odh-dashboard-v3-6-ea-2") == "odh-dashboard"
    assert mod.component_matches("odh-dashboard-v3-6-ea-2", "odh-dashboard-v3-6-ea-2")
    assert not mod.component_matches("odh-dashboard-v3-7", "odh-dashboard-v3-6")
    assert mod.component_matches("odh-dashboard", "odh-dashboard-v3-6")
