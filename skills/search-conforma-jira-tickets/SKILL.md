---
name: search-conforma-jira-tickets
description: Search for open Jira tickets (RHOAIENG, PSX, OCPEXCEPT) related to conforma violations.
allowed-tools: Bash(python3:*)
user-invocable: true
---

# Search Conforma Jira Tickets

Batch search for open Jira tickets with the `conforma-violation` label across RHOAIENG, PSX, and OCPEXCEPT projects. Matches tickets to violation rules by summary text with optional release version filtering.

## Usage

```
python3 scripts/conforma_jira_ops.py search-tickets --rules <rule1,rule2> [--releases rhoai-3.4,rhoai-3.5-ea.1]
```

## Examples

```bash
python3 scripts/conforma_jira_ops.py search-tickets --rules hermetic_task.hermetic
python3 scripts/conforma_jira_ops.py search-tickets \
  --rules "rpm_signature.allowed:9386b48a1a693c5c,hermetic_task.hermetic" \
  --releases rhoai-3.4
```

## Prerequisites

- Jira auth: `python3 scripts/jira_ops.py verify-auth`

## Output

JSON dict mapping rule to list of matching tickets:
```json
{
  "hermetic_task.hermetic": [
    {
      "key": "RHOAIENG-66102",
      "type": "Bug",
      "status": "New",
      "summary": "[Exception Approval] hermetic_task.hermetic - ...",
      "url": "https://redhat.atlassian.net/browse/RHOAIENG-66102"
    }
  ]
}
```

## Programmatic Usage

```python
import conforma_jira_ops

tickets = conforma_jira_ops.prefetch_open_jira_tickets(
    rules=["hermetic_task.hermetic"],
    releases=["rhoai-3.4"],
)
```
