---
name: analyze-mr-component-coverage
description: Check whether an open GitLab MR covers specific conforma violation components.
allowed-tools: Bash(python3:*)
user-invocable: true
---

# Analyze MR Component Coverage

Analyze which requested components an open merge request already covers for a given violation rule. Uses diff parsing as the primary method, with MR description parsing as fallback.

## Usage

```
python3 scripts/conforma_mr_ops.py analyze-coverage --mr-iid <iid> --rule <rule> --components <comp1,comp2>
```

## Examples

```bash
python3 scripts/conforma_mr_ops.py analyze-coverage \
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
  "mr_components": ["odh-dashboard-v3-4"],
  "covered": ["odh-dashboard-v3-4"],
  "missing": ["odh-model-registry-v3-4"],
  "source": "diff",
  "suggestion": "extend_mr"
}
```

The `suggestion` field is one of:
- `fully_covered` — MR covers all requested components
- `extend_mr` — MR covers some but not all; consider extending it
- `no_overlap` — MR doesn't cover any requested components

## Programmatic Usage

```python
import conforma_mr_ops

result = conforma_mr_ops.analyze_mr_component_coverage(
    mr_iid=123,
    rule="hermetic_task.hermetic",
    requested_components=["odh-dashboard-v3-4", "odh-model-registry-v3-4"],
)
```
