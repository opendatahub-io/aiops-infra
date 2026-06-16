---
name: conforma-release-readiness
description: "Answer 'Can RHOAI version X ship?' with a detailed breakdown: blocking violations, exception coverage, expiring exceptions, pending MRs, and a ship/no-ship verdict."
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
5. Checks pending MRs (exceptions in-flight but not yet merged)
6. Produces verdict: **SHIP** / **NO-SHIP** with detailed breakdown

## Workflow

When the user asks "can X ship?", "is X ready?", "release readiness for X":

### Steps

1. **Auth check**: Run auth verification for both GitHub and GitLab.

2. **Fetch violations**: Use the `conforma-analyze` skill to get current violations for the requested release.

3. **Run readiness check**:

```bash
python3 skills/conforma-release-readiness/scripts/check_readiness.py \
  --release rhoai-3.5 \
  --violations-input .work/conforma-analyze.yaml
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
| **Pending MRs** | Exception MRs not yet merged |
| **Summary** | "X of Y violations covered, Z blocking" |

## Examples

**"Can rhoai-3.5 ship?"**

```bash
python3 skills/conforma-release-readiness/scripts/check_readiness.py --release rhoai-3.5 --violations-input .work/violations.yaml
```

**"Release readiness for 3.4"**

```bash
python3 skills/conforma-release-readiness/scripts/check_readiness.py --release rhoai-3.4 --violations-input .work/violations.yaml
```
