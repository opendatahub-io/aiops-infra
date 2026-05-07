# validate-component-onboarding-jira

Pre-flight validation used at the start of every onboarding run. Fetches
`component_onboarding_details.yaml` from the Jira attachment, validates it against
the JSON schema, and runs additional checks against live systems.

## What it checks

| Check | Detail |
|-------|--------|
| Jira attachment | `component_onboarding_details.yaml` must be present |
| JSON schema | YAML is validated against `assets/component_onboarding_details.schema.json` |
| Dockerfile digests *(RHOAI only)* | Every `FROM` instruction in the Dockerfile must pin with `@sha256:` |
| Konflux component *(optional)* | Checks whether the component already exists on the target cluster via `oc get component` |

## Dockerfile digest check detail

Fetches the raw Dockerfile from GitHub at:
```
raw.githubusercontent.com/<org>/<repo>/<branch>/<dockerfile_path>
```
Any `FROM` line without `@sha256:` is reported as a violation.

## Outputs

- Prints a pass/fail summary to stdout.
- On success: sets Jira label `yaml-validated` (if not already present).
- On failure: lists each failing check with a remediation hint; does not modify Jira.

## Used by

The orchestrator ([onboard-konflux-components-for-odh-and-rhoai](onboard-konflux-components-for-odh-and-rhoai.md))
runs this skill as its first step before any repo changes are made.
