"""Tests for the optional C14 adjudication safety boundary."""

import pytest

import conforma_jira_adjudication_ops as mod


def _evidence(**overrides):
    result = {
        "classification": "possible_conforma_related",
        "component_match": True,
        "version_match": True,
        "missing_evidence": [],
        "ticket": {"key": "RHOAIENG-1"},
        "violation": {"rule": "r"},
    }
    result.update(overrides)
    return result


def test_provider_response_is_strictly_validated():
    response = mod.validate_provider_response(
        {
            "decision": "violation",
            "confidence": "high",
            "evidence_references": ["summary"],
            "reasons": "matches",
        }
    )
    assert response["decision"] == "violation"
    with pytest.raises(ValueError, match="invalid adjudication decision"):
        mod.validate_provider_response({"decision": "yes", "confidence": "high", "evidence_references": []})


def test_provider_disabled_is_explicit():
    result = mod.adjudicate_candidate(_evidence())
    assert result["status"] == "insufficient_evidence"
    assert result["reason"] == "provider_disabled"


def test_provider_cannot_override_missing_gate():
    result = mod.adjudicate_candidate(
        _evidence(version_match=False),
        lambda payload: {"decision": "violation", "confidence": "high", "evidence_references": []},
    )
    assert result["status"] == "insufficient_evidence"
    assert result["reason"] == "deterministic_gate_not_satisfied"


def test_provider_failure_and_low_confidence_are_not_matches():
    failed = mod.adjudicate_candidate(_evidence(), lambda payload: (_ for _ in ()).throw(RuntimeError("offline")))
    low = mod.adjudicate_candidate(
        _evidence(),
        lambda payload: {"decision": "violation", "confidence": "low", "evidence_references": []},
    )
    assert failed["status"] == "insufficient_evidence"
    assert low["status"] == "insufficient_evidence"
