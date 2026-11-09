# create-component-offboarding-jira

Interactively collects component parameters, generates a validated
`component_offboarding_details.yaml`, and attaches it to a Jira ticket. When no
existing ticket is provided, a new one is cloned from the offboarding template.

See the [offboarding how-to](offboarding.md) for credentials, install, and the
full run loop.

## What it produces

### component_offboarding_details.yaml

A YAML file that drives every downstream offboarding skill. Key fields:

| Field | Example |
|-------|---------|
| `product_context` | `ODH` or `RHOAI` |
| `component_name` | `odh-my-component` |
| `repo_url` | `https://github.com/org/repo` |
| `target_rhoai_version` | `3.5` or `3.5-ea-1` *(RHOAI only)* |
| `build_type` | `CI` or `Release` *(ODH only)* |
| `is_operator` | `true` / `false` |

RHOAI versions are accepted in several forms (`3.4`, `3.4.0`, `3.4-ea2`, `3.4-ea-2`,
`3.4-ea.2`, …) and normalized to canonical `x.y` or `x.y-ea-N` before writing YAML.

## Jira changes

| Action | Detail |
|--------|--------|
| New ticket (no URL given) | Clones [`RHOAIENG-32534`](https://redhat.atlassian.net/browse/RHOAIENG-32534) into `RHAI` by default; links to the parent feature; sets reporter to current user |
| Attachment | Uploads `component_offboarding_details.yaml` to the ticket |
| Labels added | `offboarding-yaml-attached`, `component-offboarding` |
| Comment | Summary of component, product, repo, operator flag |
| Summary | `[Offboarding] Konflux Offboarding <component> (<product>)` |

When updating an existing Jira URL, its project is unchanged. Newly cloned tickets go
to `RHAI` by default; set `JIRA_CREATE_PROJECT_KEY` or pass `--target-project` to
`update_offboarding_jira.py` to override it.

## Invocation

```
/create-component-offboarding-jira
/create-component-offboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234
```

See also: [validate-component-offboarding-jira](validate-component-offboarding-jira.md)
