---
name: conforma-release-readiness
description: "Answer 'Can RHOAI version X ship?' with a detailed breakdown: blocking violations, exception coverage, expiring exceptions, pending Merge Requests, and a ship/no-ship verdict."
allowed-tools: Bash(python3:*,gh:*,glab:*,git:*)
user-invocable: true
---

# Conforma Release Readiness

Answer "Can RHOAI version X ship?" with a detailed breakdown and verdict.

## Quick Start

This skill is part of the conforma suite in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

**Setup:** See [README.md](README.md) for installation and prerequisites.

## What It Does

1. Runs `conforma-analyze` to get current violations for version X
2. Fetches all active exceptions from konflux-release-data
3. Cross-references: which violations have valid exception coverage?
4. Checks exception expiry dates (warns if expiring within 14 days)
5. Checks pending Merge Requests (exceptions in-flight but not yet merged)
6. Produces verdict: **SHIP** / **NO-SHIP** with detailed breakdown

**Output presentation**: See [script-output-presentation.md](../references/script-output-presentation.md).

## Workflow

When the user asks "can X ship?", "is X ready?", "release readiness for X":

### Steps

1. **Auth check**: Run auth verification for both GitHub and GitLab.

2. **Fetch violations**: Use the `conforma-analyze` skill to get current violations for the requested release. This runs the full conforma-analyze workflow (which initializes context.yaml with the release via Step 0, resolves it via Step 2, and stores violations YAML path in context.yaml).

3. **Run readiness check**: The script reads release, environment, and violations input path from `context.yaml` automatically. Do NOT pass `--release` or `--violations-input`:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-release-readiness/scripts/check_readiness.py
```

4. **Present the verdict** to the user.

## Output

The readiness check produces:

| Section | Content |
|---------|---------|
| **Verdict** | SHIP or NO-SHIP |
| **Blocking violations** | Violations with no exception coverage |
| **Covered violations** | Violations with active exception coverage |
| **Expiring soon** | Exceptions expiring within 14 days of target date |
| **Pending Merge Requests** | Exception Merge Requests not yet merged |
| **Summary** | "X of Y violations covered, Z blocking" |

## Examples

All examples assume the conforma-analyze workflow has already run (which initializes context.yaml with the release). Do NOT pass `--release` or `--violations-input` — the script reads them from `context.yaml` automatically.

**"Can rhoai-3.5 ship?"**

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-release-readiness/scripts/check_readiness.py
```

**"Release readiness for 3.4"**

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-release-readiness/scripts/check_readiness.py
```
