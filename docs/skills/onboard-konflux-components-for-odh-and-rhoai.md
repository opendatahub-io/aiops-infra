# onboard-konflux-components-for-odh-and-rhoai

Master orchestrator that runs the full ODH/RHOAI component onboarding pipeline.
Idempotent — each invocation syncs PR/MR state, executes newly-unblocked steps, and
posts a progress update to Jira. Re-running it for the same Jira is safe and expected.

## What it does

The orchestrator does not edit files or raise PRs directly. Instead it:

1. Calls [validate-component-onboarding-jira](validate-component-onboarding-jira.md) as a pre-flight check.
2. Reads the current state of all tracked PRs/MRs from Jira labels and GitHub/GitLab APIs.
3. Determines which steps are unblocked (dependencies met, not yet started).
4. Invokes the relevant child skill for each unblocked step.
5. Posts a consolidated progress table to the Jira ticket as a comment.
6. Transitions the Jira status: `Open → In Progress → Review → Resolved`.

## Steps orchestrated

### ODH

| Step | Skill | Blocked by |
|------|-------|------------|
| 1 | create-quay-repo | — |
| 2 | onboard-component-to-konflux-release-data | — |
| 3 | add-component-to-odh-konflux-central | — |
| 4 | run-odh-konflux-onboarder-workflow | Step 3 PR merged |
| 5 | integrate-component-with-odh-operator | — *(operators only)* |
| 6 | integrate-component-with-bundle | — |

### RHOAI

| Step | Skill | Blocked by |
|------|-------|------------|
| 1 | create-quay-repo | — |
| 2 | create-rhoai-delivery-repo | — |
| 3 | onboard-component-to-konflux-release-data | — |
| 4a | add-component-to-rhoai-konflux-central | — |
| 4b | create-pull-pipelines-in-rhoai-konflux-central | — |
| 5 | integrate-component-with-odh-operator | — *(operators only)* |
| 6 | integrate-component-with-bundle | — |
| 7 | update-rhoai-product-listing | Step 2 MR merged |
| 8 | setup-auto-merge | — |
| 9a | enable-renovate-on-rhoai-component-repo | — |
| 9b | sync-rhoai-renovate-configs | Step 9a PR merged |

## Jira progress comment

Each run appends a table like the following to the Jira ticket:

```
| Step | Skill              | Status  | Link |
|------|--------------------|---------|------|
| 1    | create-quay-repo   | ✅ Done | MR#123 |
| 2    | konflux-release-data | 🔄 PR open | MR#456 |
| 3    | odh-konflux-central | ⏳ Pending | — |
```

## Jira status transitions

| Condition | Jira transition |
|-----------|----------------|
| First step starts | `Open → In Progress` |
| All PRs/MRs raised, some pending merge | `In Progress → Review` |
| All steps complete | `Review → Resolved` |

## Invocation

```
/onboard-konflux-components-for-odh-and-rhoai https://redhat.atlassian.net/browse/RHOAIENG-1234
```

Re-run any number of times. The orchestrator uses Jira labels set by each child skill
(e.g. `quay-mr-raised`, `krd-mr-raised`) as state — it will not re-raise a PR that
has already been raised.
