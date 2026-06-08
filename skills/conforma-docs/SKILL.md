---
name: conforma-docs
description: Full-text search across Conforma documentation, policy rules, exception process docs, and runbooks.
allowed-tools: Bash(python3:*)
user-invocable: true
---

# Conforma Docs

Search Conforma documentation and runbooks. This skill provides full-text search across policy rules, exception process documentation, and operational runbooks.

## Quick Start

This skill is part of the conforma suite in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

## Workflow

When the user asks about conforma documentation, policy rules, or processes:

```bash
python3 scripts/search_docs.py --query "hermetic build"
```

## Reference Data

This skill indexes:
- `references/conforma-release-policy-rules.yaml` — all conforma policy rules with codes, descriptions, and solutions
- Conforma exception process documentation
- Operational runbooks

## Examples

- "What does hermetic_task.hermetic mean?" → search for the rule definition
- "How do I create an exception?" → search exception process docs
- "What are the allowed RPM signing keys?" → search policy rules
