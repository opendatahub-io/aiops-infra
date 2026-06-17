---
name: search-conforma-existing-exceptions
description: Search konflux-release-data policy files for existing conforma exceptions matching a rule.
allowed-tools: Bash(python3:*)
user-invocable: true
---

# Search Existing Exceptions

Search the konflux-release-data policy files for existing conforma exceptions matching a violation rule. Checks both permanent global exclusions (`exclude:` section) and volatile exceptions (`volatileCriteria:` section with componentNames and effectiveUntil).

## Usage

```
python3 scripts/conforma_policy_ops.py search-exceptions --rule <rule> [--clone-dir .work/konflux-release-data]
```

## Examples

```bash
python3 scripts/conforma_policy_ops.py search-exceptions --rule hermetic_task.hermetic
python3 scripts/conforma_policy_ops.py search-exceptions \
  --rule "rpm_signature.allowed:9386b48a1a693c5c" \
  --clone-dir .work/konflux-release-data
```

## Prerequisites

- GitLab auth: `glab auth status --hostname "$GITLAB_HOST"` (for cloning the repo if no `--clone-dir`)
- Environment variables: `KONFLUX_CLUSTER_DOMAIN` or `KONFLUX_CONFORMA_POLICY_DIR`

## Output

```json
{
  "checked": true,
  "rule": "hermetic_task.hermetic",
  "existing_exceptions": [
    {
      "file": "config/.../EnterpriseContractPolicy/rhoai-prod.yaml",
      "has_componentNames": true,
      "componentNames": ["odh-model-registry-v3-4"],
      "effectiveUntil": "2026-08-12"
    }
  ],
  "permanent_exclusions": [],
  "count": 1,
  "permanent_count": 0
}
```

## Programmatic Usage

```python
import conforma_policy_ops

result = conforma_policy_ops.search_existing_exceptions(
    rule="hermetic_task.hermetic",
    clone_dir=".work/konflux-release-data",
)
```
