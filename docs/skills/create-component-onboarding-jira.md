# create-component-onboarding-jira

Interactively collects component parameters, generates a validated
`component_onboarding_details.yaml`, and attaches it to a Jira ticket. When no
existing ticket is provided, a new one is cloned from the product template.

## What it produces

### component_onboarding_details.yaml

A YAML file that drives every downstream onboarding skill. Key fields:

| Field | Example |
|-------|---------|
| `product_context` | `ODH` or `RHOAI` |
| `component_name` | `odh-my-component` |
| `repo_url` | `https://github.com/org/repo` |
| `repo_branch` | `main` or `rhoai-3.5-ea.1` |
| `context_path` | `./` |
| `dockerfile_path` | `Dockerfile.konflux` |
| `target_rhoai_version` | `3.6` or `3.6-ea-1` *(RHOAI only; drives release branch, push PipelineRun, and the main-branch pull-request PipelineRun)* / collected for ODH Jira Target Version only |
| `architectures` | `[x86_64, arm64, ppc64le, s390x]` *(RHOAI only)* |
| `long_description` / `short_description` | *(RHOAI only)* |
| `is_operator` | `true` / `false` |
| `operator_manifest_src_path` | *(operators only)* |
| `operator_manifest_dest_path` | *(operators only)* |
| `operator_manifest_type` | *(chart operators only)* — set to `chart` for Helm chart deployments |

## Jira changes

| Action | Detail |
|--------|--------|
| New ticket (no URL given) | Clones `RHOAIENG-35683` (ODH) or `RHOAIENG-17225` (RHOAI); links to the parent feature; sets reporter to current user |
| Attachment | Uploads `component_onboarding_details.yaml` to the ticket |
| Label added | `yaml-attached`, `component-onboarding`, `disable-automated-onboarding` (new tickets and existing tickets updated by this skill) |
| Comment | Summary of component, repo, branch, operator flag |
| Description table | Populated with component name, repo, branch, Dockerfile, architectures |
| Target Version | ODH: set from target RHOAI version (e.g. `3.6 EA2 RHOAI RELEASE`); RHOAI: set from derived `repo_branch` |

## Checks performed before Jira update

- **YAML schema validation** — fails hard if `component_onboarding_details.yaml`
  does not conform to the JSON schema.
- **Dockerfile digest check** *(RHOAI only)* — fails hard if any `FROM` instruction
  in the `Dockerfile.konflux` does not use a `@sha256:` digest. Skipped (with a
  notice) if the branch/file does not exist yet.

## `repo_branch` derivation (RHOAI)

The branch is never asked of the user — it is derived from `target_rhoai_version`:

| Version | Branch |
|---------|--------|
| `3.6` | `rhoai-3.6` |
| `3.6-ea-1` | `rhoai-3.6-ea.1` |

`scripts/parse_rhoai_version.sh` also turns that value into the Konflux
identifiers used by the main-branch pull-request PipelineRun. `3.6` becomes
application `rhoai-v3-6`, component `<component>-v3-6`, service account
`build-pipeline-<component>-v3-6`, and `rhoai-version` `3.6.0`. `3.6-ea-1`
becomes `v3-6-ea-1` and `3.6.0-ea.1`. The pull-request step uses this parsed
value as given. A ticket for an older release, such as `3.5`, writes
`rhoai-v3-5` into the main-branch pull-request PipelineRun. Aligning that file
with the current development application means entering the current development
version here.

See also: [validate-component-onboarding-jira](validate-component-onboarding-jira.md),
[create-pull-pipelines-in-rhoai-konflux-central](create-pull-pipelines-in-rhoai-konflux-central.md)
