"""Tests for revision-pinned structural policy exception mutation."""

from __future__ import annotations

import importlib


ops = importlib.import_module("exception_policy_file_ops")


POLICY = """spec:
  sources:
    - name: source
      volatileConfig:
        exclude:
          - value: base_image_registries.base_image_permitted:quay.io/example/image
            componentNames:
              - comp-a
              - comp-b
            effectiveUntil: '2026-10-01'
            reference: https://example.test/issue
"""


def test_preview_and_apply_removes_only_requested_component(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(POLICY, encoding="utf-8")
    record = ops.find_existing_exceptions(POLICY, "base_image_registries.base_image_permitted:quay.io/example/image")[0]

    preview = ops.preview_policy_mutation(
        path,
        {
            "operations": [
                {
                    "operation": "remove",
                    "target_fingerprint": record["entry_fingerprint"],
                    "components": ["comp-a"],
                }
            ]
        },
    )
    assert preview["status"] == "ready"

    result = ops.apply_policy_mutation(path, preview)
    assert result["status"] == "applied"
    content = path.read_text(encoding="utf-8")
    assert "comp-a" not in content
    assert "comp-b" in content
    assert "effectiveUntil: '2026-10-01'" in content


def test_extend_is_structural_and_dry_run_does_not_write(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(POLICY, encoding="utf-8")
    record = ops.find_existing_exceptions(POLICY, "base_image_registries.base_image_permitted")[0]
    preview = ops.preview_policy_mutation(
        path,
        {
            "operations": [
                {
                    "operation": "extend",
                    "target_fingerprint": record["entry_fingerprint"],
                    "effective_until": "2026-11-01",
                }
            ]
        },
    )
    result = ops.apply_policy_mutation(path, preview, dry_run=True)
    assert result["status"] == "dry_run"
    assert "2026-11-01" not in path.read_text(encoding="utf-8")


def test_broader_exception_requires_explicit_choice(tmp_path):
    path = tmp_path / "policy.yaml"
    broader = POLICY.replace("            componentNames:\n              - comp-a\n              - comp-b\n", "")
    path.write_text(broader, encoding="utf-8")
    preview = ops.preview_policy_mutation(
        path,
        {
            "operations": [
                {
                    "operation": "add",
                    "rule": "base_image_registries.base_image_permitted",
                    "components": ["comp-a"],
                    "entry": {
                        "value": "base_image_registries.base_image_permitted:quay.io/example/image",
                        "componentNames": ["comp-a"],
                        "effectiveUntil": "2026-10-01",
                    },
                }
            ]
        },
    )
    assert preview["status"] == "confirmation_required"
    assert {choice["choice_id"] for choice in preview["decisions"][0]["choices"]} == {
        "keep_broader",
        "add_scoped",
    }

    result = ops.apply_policy_mutation(
        path,
        preview,
        selections={"decision-1": "keep_broader"},
    )
    assert result["status"] == "no_change_required"
    assert path.read_text(encoding="utf-8") == broader


def test_stale_preview_is_rejected(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(POLICY, encoding="utf-8")
    preview = ops.preview_policy_mutation(path, {"operations": []})
    path.write_text(POLICY + "\n", encoding="utf-8")
    result = ops.apply_policy_mutation(path, preview)
    assert result["status"] == "stale"
