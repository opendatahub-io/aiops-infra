# add-rhoai-dockerfile-labels

Ensures the component's `Dockerfile.konflux` contains all seven mandatory RHOAI OCI
labels. Missing labels are injected and a PR is raised.

**Applies to:** RHOAI only  
**Invoked:** Standalone (not part of the main orchestrator pipeline)

## Repository touched

The component's own GitHub repository (value of `repo_url` in
`component_onboarding_details.yaml`).

## File modified

```
<dockerfile_path>   (e.g. Dockerfile.konflux)
```

The seven mandatory labels are inserted as a `LABEL` block immediately after the last
`FROM` statement in the Dockerfile:

```dockerfile
LABEL name="<component_name>" \
      com.redhat.component="<component_name>" \
      summary="<short_description>" \
      description="<long_description>" \
      maintainer="Red Hat, Inc." \
      io.k8s.display-name="<short_description>" \
      io.k8s.description="<long_description>"
```

Only labels that are **absent** from the existing file are added — existing labels are
left untouched.

## PR raised

| Field | Value |
|-------|-------|
| Target repo | Component repo (`repo_url`) |
| Target branch | `main` |
| Title | `add required OCI labels to Dockerfile.konflux` |

## Jira update

Label added: `dockerfile-labels-pr-raised`  
Comment: PR URL posted to the onboarding ticket.

## When it is needed

This skill is typically run when a component's Dockerfile is missing labels that are
required by Conforma/Enterprise Contract policy. It is independent of the main pipeline
and can be run at any point after the Jira ticket has a valid `component_onboarding_details.yaml`.
