# ODH / RHOAI Component Onboarding Skills

This directory documents the individual Claude Code skills that automate component
onboarding onto the Konflux CI/CD platform. Each skill doc focuses on **what changes
are made and where** — prerequisites, credentials, and tool setup are not repeated
per skill.

## Pipeline overview

The master orchestrator `/onboard-konflux-components-for-odh-and-rhoai` coordinates
all steps below. Steps are idempotent — re-running the orchestrator picks up where it
left off.

### ODH pipeline

| Step | Skill | Target |
|------|-------|--------|
| 0 | [create-component-onboarding-jira](create-component-onboarding-jira.md) | Jira (new ticket) |
| — | [validate-component-onboarding-jira](validate-component-onboarding-jira.md) | Jira (pre-flight check) |
| 1 | [create-quay-repo](create-quay-repo.md) | `app-interface` GitLab MR |
| 2 | [onboard-component-to-konflux-release-data](onboard-component-to-konflux-release-data.md) | `konflux-release-data` GitLab MR |
| 3 | [add-component-to-odh-konflux-central](add-component-to-odh-konflux-central.md) | `odh-konflux-central` GitHub PR |
| 4 | [run-odh-konflux-onboarder-workflow](run-odh-konflux-onboarder-workflow.md) | GitHub Actions → Tekton PR |
| 5 | [integrate-component-with-odh-operator](integrate-component-with-odh-operator.md) | `opendatahub-operator` GitHub PR *(operators only)* |
| 6 | [integrate-component-with-bundle](integrate-component-with-bundle.md) | `ODH-Build-Config` GitHub PR |

### RHOAI pipeline

| Step | Skill | Target |
|------|-------|--------|
| 0 | [create-component-onboarding-jira](create-component-onboarding-jira.md) | Jira (new ticket) |
| — | [validate-component-onboarding-jira](validate-component-onboarding-jira.md) | Jira (pre-flight check) |
| 1 | [create-quay-repo](create-quay-repo.md) | `app-interface` GitLab MR |
| 2 | [create-rhoai-delivery-repo](create-rhoai-delivery-repo.md) | `pyxis-repo-configs` GitLab MR |
| 3 | [onboard-component-to-konflux-release-data](onboard-component-to-konflux-release-data.md) | `konflux-release-data` GitLab MR |
| 4 | [add-component-to-rhoai-konflux-central](add-component-to-rhoai-konflux-central.md) | `konflux-central` GitHub PR (push pipeline) |
| 4 | [create-pull-pipelines-in-rhoai-konflux-central](create-pull-pipelines-in-rhoai-konflux-central.md) | `konflux-central` GitHub PR (pull-request pipeline) |
| 5 | [integrate-component-with-odh-operator](integrate-component-with-odh-operator.md) | `rhods-operator` GitHub PR *(operators only)* |
| 6 | [integrate-component-with-bundle](integrate-component-with-bundle.md) | `RHOAI-Build-Config` GitHub PR |
| 7 | [update-rhoai-product-listing](update-rhoai-product-listing.md) | `pyxis-repo-configs` GitLab MR |
| 8 | [setup-auto-merge](setup-auto-merge.md) | `rhods-devops-infra` GitHub PR |
| 9 | [enable-renovate-on-rhoai-component-repo](enable-renovate-on-rhoai-component-repo.md) | `konflux-central` GitHub PR |
| 9 | [sync-rhoai-renovate-configs](sync-rhoai-renovate-configs.md) | GitHub Actions workflow |

### Supplementary skills

| Skill | Purpose |
|-------|---------|
| [add-rhoai-dockerfile-labels](add-rhoai-dockerfile-labels.md) | Ensure mandatory OCI labels are present in the component Dockerfile |
| [onboard-konflux-components-for-odh-and-rhoai](onboard-konflux-components-for-odh-and-rhoai.md) | Master orchestrator — runs all pipeline steps above |

## Key repositories

| Repo | Host | Used by |
|------|------|---------|
| `opendatahub-io/odh-konflux-central` | GitHub | add-component-to-odh-konflux-central, run-odh-konflux-onboarder-workflow |
| `red-hat-data-services/konflux-central` | GitHub | add-component-to-rhoai-konflux-central, create-pull-pipelines, enable-renovate, sync-renovate |
| `releng/konflux-release-data` | GitLab (cee) | onboard-component-to-konflux-release-data |
| `service/app-interface` | GitLab (cee) | create-quay-repo |
| `releng/pyxis-repo-configs` | GitLab (cee) | create-rhoai-delivery-repo, update-rhoai-product-listing |
| `opendatahub-io/ODH-Build-Config` | GitHub | integrate-component-with-bundle (ODH) |
| `red-hat-data-services/RHOAI-Build-Config` | GitHub | integrate-component-with-bundle (RHOAI) |
| `opendatahub-io/opendatahub-operator` | GitHub | integrate-component-with-odh-operator (ODH) |
| `red-hat-data-services/rhods-operator` | GitHub | integrate-component-with-odh-operator (RHOAI) |
| `red-hat-data-services/rhods-devops-infra` | GitHub | setup-auto-merge |
| Component repo | GitHub | add-rhoai-dockerfile-labels |
