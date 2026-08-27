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
| `target_rhoai_version` | `3.5-ea-1` *(RHOAI only)* |
| `architectures` | `[x86_64, arm64, ppc64le, s390x]` *(RHOAI only)* |
| `long_description` / `short_description` | *(RHOAI only)* |
| `is_operator` | `true` / `false` |
| `operator_manifest_src_path` | *(operators only)* |
| `operator_manifest_dest_path` | *(operators only)* |

## Jira changes

| Action | Detail |
|--------|--------|
| New ticket (no URL given) | Clones `RHOAIENG-35683` (ODH) or `RHOAIENG-17225` (RHOAI); links to the parent feature; sets reporter to current user |
| Attachment | Uploads `component_onboarding_details.yaml` to the ticket |
| Label added | `yaml-attached`, `component-onboarding`, `disable-automated-onboarding` (new tickets and existing tickets updated by this skill) |
| Comment | Summary of component, repo, branch, operator flag |
| Description table | Populated with component name, repo, branch, Dockerfile, architectures |

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
| `3.5` | `rhoai-3.5` |
| `3.5-ea-1` | `rhoai-3.5-ea.1` |

See also: [validate-component-onboarding-jira](validate-component-onboarding-jira.md)
