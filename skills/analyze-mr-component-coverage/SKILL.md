---
name: analyze-mr-component-coverage
description: Check whether an open GitLab Merge Request covers specific conforma violation components.
allowed-tools: Bash(python3:*)
user-invocable: true
---

# Analyze Merge Request Component Coverage

Analyze which requested components an open Merge Request already covers for a given violation rule. Uses diff parsing as the primary method, with Merge Request description parsing as fallback. Each result includes `mr_type` (`exception` or `remedy`) based on the changed file paths.

## Usage

```
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/conforma_mr_ops.py" analyze-coverage --mr-iid <iid> --rule <rule> --components <comp1,comp2>
```

## Examples

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/conforma_mr_ops.py" analyze-coverage \
  --mr-iid 123 \
  --rule hermetic_task.hermetic \
  --components odh-dashboard-v3-4,odh-model-registry-v3-4
```

## Prerequisites

- GitLab auth: `glab auth status --hostname "$GITLAB_HOST"`

## Output

JSON dict with coverage analysis:
```json
{
  "mr_iid": 123,
  "mr_type": "exception",
  "mr_components": ["odh-dashboard-v3-4"],
  "covered": ["odh-dashboard-v3-4"],
  "missing": ["odh-model-registry-v3-4"],
  "source": "diff",
  "suggestion": "extend_mr"
}
```

The `mr_type` field is deterministic — based on changed file paths:
- `exception` — Merge Request modifies conforma registry files (`EnterpriseContractPolicy/`, `exceptions/`)
- `remedy` — Merge Request modifies other files (component fix, build config, etc.)

The `suggestion` field is one of:
- `fully_covered` — Merge Request covers all requested components
- `extend_mr` — Merge Request covers some but not all; consider extending it
- `no_overlap` — Merge Request doesn't cover any requested components

## Programmatic Usage

```python
import conforma_mr_ops

result = conforma_mr_ops.analyze_mr_component_coverage(
    mr_iid=123,
    rule="hermetic_task.hermetic",
    requested_components=["odh-dashboard-v3-4", "odh-model-registry-v3-4"],
)
```
