"""Optional advisory adjudication for ambiguous C14 Jira evidence.

This module owns only the provider contract and deterministic safety boundary.
It never calls Jira and never turns missing evidence into a confirmed match.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable

ALLOWED_DECISIONS = {"violation", "general", "unrelated", "uncertain"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}


def validate_provider_response(response: dict) -> dict:
    """Validate and normalize a structured provider response."""
    if not isinstance(response, dict):
        raise ValueError("adjudication response must be a mapping")
    decision = response.get("decision")
    confidence = response.get("confidence")
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"invalid adjudication decision: {decision!r}")
    if confidence not in ALLOWED_CONFIDENCE:
        raise ValueError(f"invalid adjudication confidence: {confidence!r}")
    evidence_references = response.get("evidence_references")
    if not isinstance(evidence_references, list) or not all(isinstance(item, str) for item in evidence_references):
        raise ValueError("evidence_references must be a list of strings")
    return {
        "decision": decision,
        "confidence": confidence,
        "matched_rule": response.get("matched_rule"),
        "matched_component": response.get("matched_component"),
        "matched_release": response.get("matched_release"),
        "evidence_references": evidence_references,
        "reasons": str(response.get("reasons") or ""),
        "missing_evidence_acknowledged": bool(response.get("missing_evidence_acknowledged")),
    }


def adjudicate_candidate(
    evidence: dict,
    provider: Callable[[dict], dict] | None = None,
) -> dict:
    """Adjudicate one ambiguous candidate, preserving deterministic safety."""
    if evidence.get("classification") != "possible_conforma_related":
        return {"status": "not_applicable", "evidence": evidence}
    if provider is None:
        return {
            "status": "insufficient_evidence",
            "reason": "provider_disabled",
            "evidence": evidence,
        }
    payload = {
        "ticket": evidence.get("ticket", {}),
        "violation": evidence.get("violation", {}),
        "deterministic_evidence": {
            key: evidence.get(key)
            for key in (
                "component_match",
                "version_match",
                "rule_match",
                "label_match",
                "release_relevance",
                "missing_evidence",
                "component_evidence",
                "version_evidence",
            )
        },
    }
    try:
        response = validate_provider_response(provider(payload))
    except Exception as exc:  # provider errors are reported, never treated as a match
        return {"status": "insufficient_evidence", "reason": f"provider_error: {exc}", "evidence": evidence}
    if response["confidence"] == "low" or response["decision"] == "uncertain":
        return {"status": "insufficient_evidence", "reason": "low_confidence_or_uncertain", "response": response}
    if response["decision"] == "violation" and evidence.get("component_match") and evidence.get("version_match"):
        return {"status": "adjudicated_violation", "response": response, "evidence": evidence}
    return {"status": "insufficient_evidence", "reason": "deterministic_gate_not_satisfied", "response": response}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a C14 Jira adjudication response")
    parser.add_argument("--response", required=True, help="JSON object containing the provider response")
    args = parser.parse_args()
    print(json.dumps(validate_provider_response(json.loads(args.response)), indent=2))


if __name__ == "__main__":
    main()
