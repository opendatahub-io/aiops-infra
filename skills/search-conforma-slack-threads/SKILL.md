---
name: search-conforma-slack-threads
description: Search Slack for recent threads discussing conforma violation rules.
allowed-tools: Bash(python3:*)
user-invocable: true
---

# Search Conforma Slack Threads

Search Slack for messages mentioning conforma violation rules from the last 30 days. Results are grouped by thread and optionally filtered to threads mentioning specific components.

## Usage

```
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/conforma_slack_ops.py" search-threads --rules <rule1,rule2> [--components <comp1,comp2>]
```

## Examples

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/conforma_slack_ops.py" search-threads --rules trusted_task.trusted
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/conforma_slack_ops.py" search-threads \
  --rules "rpm_signature.allowed:8a3872bf3228467c" \
  --components odh-spark-operator-v3-4,odh-vllm-cpu-v3-4
```

## Prerequisites

- Slack auth: `_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/slack_ops.py" verify-auth`

## Output

JSON dict mapping rule to list of matching Slack threads:
```json
{
  "trusted_task.trusted": [
    {
      "channel": "konflux-users",
      "channel_id": "C04PZ7H0VA8",
      "permalink": "https://redhat-internal.slack.com/archives/...",
      "thread_ts": "1780580263.475819",
      "thread_reply_count": 5,
      "user": "username",
      "date": "2026-06-04"
    }
  ]
}
```

## Programmatic Usage

```python
import conforma_slack_ops

threads = conforma_slack_ops.prefetch_open_slack_threads(
    rules=["trusted_task.trusted"],
    rule_to_components={"trusted_task.trusted": ["odh-dashboard-v3-4"]},
)
```
