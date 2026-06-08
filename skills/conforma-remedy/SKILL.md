---
name: conforma-remedy
description: Find and apply fixes to underlying conforma violations in component code, configs, or build pipelines.
allowed-tools: Bash(python3:*,gh:*,git:*)
user-invocable: true
---

# Conforma Remedy

Find and apply fixes to underlying conforma violations. This skill focuses on resolving violations in component code, configuration, or build pipelines — the preferred path before creating exceptions.

## Quick Start

This skill is part of the conforma suite in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

## Violations-First Philosophy

This skill embodies the core principle: **fix the violation, don't just waive it.** Exceptions should only be created when a code fix is genuinely not feasible within the release timeline.

## Common Fixes by Violation Type

### `hermetic_task.hermetic` — Enable hermetic builds

Set `HERMETIC=true` in the Tekton PipelineRun YAML for the component's build task.

### `trusted_task.trusted` — Upgrade to trusted task version

Upgrade the `prefetch-dependencies` task (or other untrusted tasks) to the latest trusted version. Check the task bundle reference SHA in the component's PipelineRun.

### `prefetch_dependencies.mode_not_permissive` — Fix prefetch mode

Change the `prefetch-dependencies` task mode from `permissive` to a secure value in the PipelineRun YAML.

### `prefetch_dependencies.package_registry_proxy_enabled` — Enable package registry proxy

Set `enable-package-registry-proxy=true` in the `prefetch-dependencies` task parameters.

### `rpm_signature.allowed` — Fix RPM signing

Ensure RPMs use an allowed signing key, or get the additional key approved by the release engineering team. This often requires coordination with upstream package maintainers.

### `test.no_failed_tests` — Fix failing tests

Investigate and fix the failing integration/enterprise contract tests. These violations indicate real test failures that need addressing.

## Workflow

When the user asks to fix/remedy/resolve a violation:

1. Identify the violation type and affected components
2. Look up the appropriate fix from the table above
3. Locate the component's build configuration (PipelineRun YAML)
4. Apply the fix
5. Verify the fix by checking if the violation clears on the next build

## Status

This skill is in early development. Currently provides guidance and fix templates. Future versions will include automated fix scripts.
