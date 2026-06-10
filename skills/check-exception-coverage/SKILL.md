---
name: check-exception-coverage
description: Check if existing policy exceptions and open MRs cover specific components for a violation rule.
allowed-tools: Bash(python3:*)
user-invocable: true
---

# Check Exception Coverage

Determine whether existing policy exceptions and open merge requests in konflux-release-data cover specific components for a given violation rule. This is the coverage gate used by the violations analysis workflow.

## Usage

```
python3 scripts/conforma_policy_ops.py check-gate --rule <rule> --components <comp1,comp2> [--clone-dir .work/konflux-release-data] [--environment prod]
```

## Examples

```bash
python3 scripts/conforma_policy_ops.py check-gate \
  --rule hermetic_task.hermetic \
  --components odh-model-registry-v3-4
python3 scripts/conforma_policy_ops.py check-gate \
  --rule "rpm_signature.allowed:9386b48a1a693c5c" \
  --components odh-training-rocm64-torch28-py312-v3-4,odh-training-rocm64-torch29-py312-v3-4 \
  --clone-dir .work/konflux-release-data \
  --environment prod
```

## Prerequisites

- GitLab auth: `glab auth status --hostname "$GITLAB_HOST"`
- Environment variables: `GITLAB_HOST`, `GITLAB_TOKEN`, `KRD_CLUSTER_DOMAIN` or `KRD_EC_POLICY_DIR`

## Output

```json
{
  "gate": "existing_exception_check",
  "status": "partial",
  "reason": "1 of 2 component(s) already covered...",
  "rule": "rpm_signature.allowed:9386b48a1a693c5c",
  "requested_components": ["comp-a", "comp-b"],
  "active_exceptions": [...],
  "permanent_exclusions": [],
  "covered_components": ["comp-a"],
  "uncovered_components": ["comp-b"],
  "open_merge_requests": [...]
}
```

The `status` field is one of:
- `blocked` — all components already covered by active exceptions
- `partial` — some components covered, some uncovered
- `passed` — no active exceptions found; proceed with creation
- `permanent` — rule is permanently excluded globally

## Programmatic Usage

```python
import conforma_policy_ops

result = conforma_policy_ops.check_existing_exception_gate(
    rule="hermetic_task.hermetic",
    components=["odh-model-registry-v3-4"],
    clone_dir=".work/konflux-release-data",
    environment="prod",
)
```
