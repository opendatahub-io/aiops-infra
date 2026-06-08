---
name: conforma-exception-manage
description: Find and assess expired conforma exceptions, generate reports, and execute interactive action loops for cleanup.
allowed-tools: Bash(python3:*,glab:*,acli:*,gh:*,git:*)
user-invocable: true
---

# Conforma Exception Manage

Find and assess expired or active conforma exceptions. Generate reports showing which exceptions are still needed, which can be removed, and which need extending. Supports interactive action loops for batch cleanup.

## Quick Start

This skill is part of the conforma suite in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

**Prerequisites:**
- `gh` CLI authenticated
- `glab` CLI authenticated
- Read access to `red-hat-data-services/conforma-reporter` (private)

## Workflow

This skill orchestrates the `conforma-analyze` and `conforma-exception` skills to manage exception lifecycle.

### Find expired exceptions

```bash
python3 skills/conforma-exception/scripts/manage_exceptions.py --find-expired --environment prod
```

### Assess expired exceptions against current violations

1. First, run `conforma-analyze` to get current violations
2. Then assess:

```bash
python3 skills/conforma-exception/scripts/manage_exceptions.py --assess-expired \
  --violations-input .work/conforma-analyze.yaml \
  --environment prod \
  --output .work/assessed-exceptions.yaml
```

3. Generate a human-readable report:

```bash
python3 skills/conforma-exception/scripts/generate_report.py \
  --assessed-input .work/assessed-exceptions.yaml \
  --output .work/exception-report.md
```

### Interactive action loop

After assessment, present the user with each exception and its recommended action:

| Classification | Recommended Action |
|----------------|-------------------|
| `no_longer_needed` | Remove the exception from the policy file |
| `still_needed` | Extend the effectiveUntil date |
| `partially_needed` | Narrow to only the still-violating components and extend |

For each exception, confirm the action with the user before executing.
