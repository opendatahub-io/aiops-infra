---
name: search-conforma-open-exception-mrs
description: Search for open GitLab Merge Requests in konflux-release-data that match a conforma violation rule.
allowed-tools: Bash(python3:*)
user-invocable: true
---

# Search Open Exception Merge Requests

Search for open Merge Requests in the konflux-release-data GitLab repository that mention a conforma violation rule. Performs two searches (full rule + suffix after `:`) and deduplicates by Merge Request `iid`.

## Usage

```
python3 scripts/conforma_mr_ops.py search-open-mrs --rule <rule>
```

## Examples

```bash
python3 scripts/conforma_mr_ops.py search-open-mrs --rule hermetic_task.hermetic
python3 scripts/conforma_mr_ops.py search-open-mrs --rule "rpm_signature.allowed:9386b48a1a693c5c"
```

## Prerequisites

- GitLab auth: `glab auth status --hostname "$GITLAB_HOST"`
- Environment variables: `GITLAB_HOST`, `GITLAB_TOKEN`

## Output

JSON list of Merge Request dicts:
```json
[
  {
    "iid": 123,
    "title": "Conforma exception for hermetic_task.hermetic",
    "url": "https://gitlab.example.com/.../merge_requests/123",
    "author": "username",
    "created_at": "2026-06-01T12:00:00Z",
    "description": "..."
  }
]
```

## Programmatic Usage

```python
import conforma_mr_ops

mrs = conforma_mr_ops.search_open_exception_mrs("hermetic_task.hermetic")
```
