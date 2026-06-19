# onboard-konflux-components-for-odh-and-rhoai

Master orchestrator that runs the full ODH/RHOAI component onboarding pipeline.
Idempotent — each invocation syncs PR/MR state, executes newly-unblocked steps, and
posts a progress update to Jira. Re-running it for the same Jira is safe and expected.

## What it does

The orchestrator does not edit files or raise PRs directly. Instead it:

1. Calls [validate-component-onboarding-jira](validate-component-onboarding-jira.md) as a pre-flight check.
2. Reads the current state of all tracked Pull Requests / Merge Requests from Jira labels and GitHub/GitLab APIs.
3. Determines which steps are unblocked (all `depends_on` steps are merged/done).
4. Invokes the relevant child skill for each unblocked step.
5. Posts a consolidated progress table to the Jira ticket as a comment.
6. Transitions the Jira status: `Open -> In Progress -> Review -> Resolved`.

## Steps orchestrated

### ODH

| Step | Skill | Blocked by |
|------|-------|------------|
| 1 | [create-quay-repo](create-quay-repo.md) | — |
| 2 | [add-component-to-odh-konflux-central](add-component-to-odh-konflux-central.md) | — |
| 3 | [onboard-component-to-konflux-release-data](onboard-component-to-konflux-release-data.md) | quay merged |
| 4 | [run-odh-konflux-onboarder-workflow](run-odh-konflux-onboarder-workflow.md) | krd + okc merged |
| 5 | [integrate-component-with-bundle](integrate-component-with-bundle.md) | onboarder_workflow merged |
| 6 | [integrate-component-with-odh-operator](integrate-component-with-odh-operator.md) | bundle merged *(operators only)* |

### RHOAI

| Step | Skill | Blocked by |
|------|-------|------------|
| 1 | [create-quay-repo](create-quay-repo.md) | — |
| 2 | [create-rhoai-delivery-repo](create-rhoai-delivery-repo.md) | — |
| 3 | [enable-renovate-on-rhoai-component-repo](enable-renovate-on-rhoai-component-repo.md) | — |
| 4 | [setup-auto-merge](setup-auto-merge.md) | — |
| 5 | [onboard-component-to-konflux-release-data](onboard-component-to-konflux-release-data.md) | quay + delivery_repo merged |
| 6 | [update-rhoai-product-listing](update-rhoai-product-listing.md) | delivery_repo merged |
| 7 | [sync-rhoai-renovate-configs](sync-rhoai-renovate-configs.md) | renovate merged |
| 8a | [add-component-to-rhoai-konflux-central](add-component-to-rhoai-konflux-central.md) | krd merged |
| 8b | [create-pull-pipelines-in-rhoai-konflux-central](create-pull-pipelines-in-rhoai-konflux-central.md) | krd merged |
| 9 | [integrate-component-with-bundle](integrate-component-with-bundle.md) | okc merged |
| 10 | [integrate-component-with-odh-operator](integrate-component-with-odh-operator.md) | bundle merged *(operators only)* |

## Jira progress comment

Each run appends a table like the following to the Jira ticket (only when something changed):

```
| Step | Skill              | Status  | Link |
|------|--------------------|---------|------|
| 1    | create-quay-repo   | Done    | MR#123 |
| 2    | konflux-release-data | PR open | MR#456 |
| 3    | odh-konflux-central | Pending | — |
```

## Jira status transitions

| Condition | Jira transition |
|-----------|----------------|
| First step starts | `Open -> In Progress` |
| All Pull Requests / Merge Requests raised, some pending merge | `In Progress -> Review` |
| All steps complete | `Review -> Resolved` |

## Invocation

```
/onboard-konflux-components-for-odh-and-rhoai https://redhat.atlassian.net/browse/RHOAIENG-1234
```

Re-run any number of times. The orchestrator uses Jira labels set by each child skill
(e.g. `quay-mr-raised`, `krd-mr-raised`) as state — it will not re-raise a PR that
has already been raised.
