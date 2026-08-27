# validate-component-offboarding-jira

Pre-flight validation used at the start of every offboarding run. Fetches
`component_offboarding_details.yaml` from the Jira attachment and validates it
against the JSON schema.

## What it checks

| Check | Detail |
|-------|--------|
| Jira attachment | `component_offboarding_details.yaml` must be present |
| JSON schema | YAML is validated against `schemas/component_offboarding_details.schema.json` |
| RHOAI required fields | `target_rhoai_version` in canonical form (`3.4` or `3.4-ea-2`) |
| ODH required fields | `build_type` (`CI` or `Release`) |

Any failure is a hard blocker. The ticket is labelled `validation-failed` with a
comment describing the error.

## Outputs

- On success: label `validation-successful`, status `In Progress`.
- On failure: lists each failing check; does not start removal steps.

## Used by

The orchestrator ([offboard-konflux-components-for-odh-and-rhoai](offboard-konflux-components-for-odh-and-rhoai.md))
runs this skill as its first step before any repo changes are made.

## Invocation

```
/validate-component-offboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234
```
