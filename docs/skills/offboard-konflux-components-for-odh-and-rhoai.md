# offboard-konflux-components-for-odh-and-rhoai

Master orchestrator that runs the full ODH/RHOAI component offboarding pipeline.
Idempotent — each invocation syncs PR/MR state, executes newly-unblocked steps, and
posts a progress update to Jira. Re-running it for the same Jira is safe and expected.

For install, credentials, dry-run, and the create-Jira flow, see the
[offboarding how-to](offboarding.md).

## What it does

The orchestrator does not edit files or raise PRs directly. Instead it:

1. Calls [validate-component-offboarding-jira](validate-component-offboarding-jira.md) as a pre-flight check.
2. Reads the current state of all tracked PRs/MRs from GitHub/GitLab APIs.
3. Determines which steps are unblocked (all `depends_on` steps are merged/done/skipped).
4. Invokes the relevant step script for each unblocked step.
5. Posts a consolidated progress table to the Jira ticket as a comment (only when something changed).
6. Transitions the Jira status: `In Progress` → `Review` → `Resolved`.

Closed-without-merge PRs/MRs are reset to `pending` so the next run re-raises them.

## Steps orchestrated

Removal PRs/MRs for KRD, OKC, pull pipelines, bundle, and operator are independent
and can run in parallel. Tekton cleanup waits on OKC/pull-pipeline merges. Component
CR deletion waits on every other step and requires human confirmation.

| Step | Target | Blocked by |
|------|--------|------------|
| 1 | [validate-component-offboarding-jira](validate-component-offboarding-jira.md) | — |
| 2 | `konflux-release-data` GitLab MR (`remove_krd`) | — |
| 3 | Konflux Central GitHub PR, push PipelineRun (`remove_okc`) | — |
| 4 | Konflux Central GitHub PR, pull-request PipelineRun (`remove_pull_pipelines`) | — *(RHOAI only)* |
| 5 | ODH/RHOAI Build-Config GitHub PR (`remove_bundle`) | — |
| 6 | odh-operator / rhods-operator GitHub PR (`remove_operator`) | — *(operators only)* |
| 7 | Component repo `.tekton/` GitHub PR (`sync_component_tekton`) | okc + pull_pipelines merged/skipped |
| 8 | Delete Konflux `Component` CR (`remove_component_cr`) | all prior steps; **confirmation required** |

Not removed automatically: Quay repositories, RHOAI product-listing entries.

## Isolation from onboarding

Offboarding is purely additive. Shared onboarding scripts are not modified; where
behaviour differs, offboarding ships its own copy (`edit_offboarding_yaml.py`,
`update_offboarding_jira.py`, `check_offboarding_prerequisites.sh`,
`check_offboarding_pr_mr_status.sh`, `raise_offboarding_jira_review.sh`).

## Jira status transitions

| Condition | Jira transition |
|-----------|-----------------|
| First successful validate | `In Progress` |
| PRs/MRs raised, some pending merge | `In Progress` → `Review` (`offboarding-in-review`) |
| All steps complete | `Review` → `Resolved` (`component-offboarding-completed`) |

## Invocation

```
/offboard-konflux-components-for-odh-and-rhoai https://redhat.atlassian.net/browse/RHOAIENG-1234
```

Dry run:

```bash
export OFFBOARD_DRY_RUN=true
```
