# Approach 2: Claude Code / Cursor Skills — Local Execution

## Overview

The ODH component onboarding workflow is implemented as a **suite of modular Claude Code skills**, each responsible for one discrete step of the pipeline. A component team member first runs the `create-component-onboarding-jira` skill to create the Jira ticket and capture onboarding parameters. The DevOps engineer then invokes the `onboard-konflux-components-for-odh-and-rhoai` wrapper skill with the Jira URL; the wrapper reads the attached YAML, executes each step skill in sequence, raises PRs/MRs to the target repositories, and launches background monitors to track merges. Jira is updated automatically at each milestone, and the ticket transitions to "Resolved" once all PRs and MRs are merged.

All skills run **locally** in the engineer's Claude Code / Cursor IDE session. A planned follow-on phase will automatically trigger the wrapper skill on Jira ticket creation via a webhook or CI pipeline, eliminating the manual invocation step.

---

## Skill Directory Structure

All skills live under `.claude/skills/` in the `aiops-infra` repository:

```
.claude/skills/
├── create-component-onboarding-jira/     # Run by component teams (independent)
│   ├── SKILL.md
│   └── install.sh
├── validate-component-onboarding-jira/   # Step 1: fetch + validate Jira YAML
│   ├── SKILL.md
│   ├── install.sh
│   └── assets/
│       └── component_onboarding_details.schema.json
├── create-quay-repo/                     # Step 2: GitLab MR to app-interface
│   ├── SKILL.md
│   └── install.sh
├── onboard-component-to-konflux-release-data/  # Step 3: GitLab MR to konflux-release-data
│   ├── SKILL.md
│   └── install.sh
├── add-component-to-odh-konflux-central/       # Step 4: GitHub PR for Tekton pipelineruns
│   ├── SKILL.md
│   └── install.sh
├── run-odh-konflux-onboarder-workflow/         # Step 5: GitHub Actions workflow trigger
│   ├── SKILL.md
│   └── install.sh
├── integrate-component-with-odh-operator/      # Step 6: GitHub PR to opendatahub-operator (conditional)
│   ├── SKILL.md
│   └── install.sh
├── integrate-component-with-bundle/            # Step 7: GitHub PR to ODH-Build-Config
│   ├── SKILL.md
│   └── install.sh
├── onboard-konflux-components-for-odh-and-rhoai/  # Wrapper — orchestrates Steps 1–7
│   ├── SKILL.md
│   └── install.sh
└── common/
    └── scripts/                          # Shared helper scripts used across skills
        ├── fetch_jira_details.py
        ├── update_jira_issue.py
        ├── validate_yaml_schema.py
        ├── download_jira_attachment.py
        ├── setup_github_fork.py
        ├── raise_github_pr.py
        ├── monitor_github_pr.py
        ├── setup_gitlab_fork.py
        ├── raise_gitlab_mr.py
        ├── monitor_gitlab_mr.py
        ├── run_github_workflow.py
        ├── check_quay_repo.sh
        ├── check_konflux_component.sh
        ├── login_to_konflux_cluster.sh
        ├── launch_monitor.sh             # Launches background PR/MR monitors
        ├── monitor_pr.sh                 # Worker: retry loop + Jira update on merge
        └── watch_monitors.sh             # Live event stream across all monitors
```

---

## Architecture Diagram

```mermaid
flowchart TD
    subgraph componentTeam [Component Team]
        CT([Component Engineer])
        createJira["create-component-onboarding-jira\n(independent skill)"]
        CT -->|"Fill onboarding details"| createJira
        createJira -->|"Attach YAML + post comment"| JiraTicket
    end

    subgraph devopsEngineer [DevOps Engineer — Claude Code / Cursor]
        Eng([DevOps Engineer])
        Wrapper["onboard-konflux-components-for-odh-and-rhoai\n(wrapper skill)"]
        State["pipeline_state.json\n(resumable state)"]

        S1["validate-component-onboarding-jira"]
        S2["create-quay-repo"]
        S3["onboard-component-to-konflux-release-data"]
        S4["add-component-to-odh-konflux-central"]
        S5["run-odh-konflux-onboarder-workflow\n(deferred, background)"]
        S6["integrate-component-with-odh-operator\n(if is_operator=true)"]
        S7["integrate-component-with-bundle"]
        BG["Background monitors\n(launch_monitor.sh / monitor_completion.sh)"]

        Eng -->|"/onboard-konflux-components-for-odh-and-rhoai <jira-url>"| Wrapper
        Wrapper --> S1 --> S2 --> S3 --> S4 --> S5
        S4 --> S6 --> S7
        Wrapper --> BG
        Wrapper <-->|"Read / Write"| State
    end

    subgraph jiraLayer [Jira — RHOAIENG / RHODS Project]
        JiraTicket["Onboarding Ticket\n(YAML attachment, labels, status)"]
    end

    subgraph externalSystems [External Systems]
        AppInterface["app-interface (GitLab)"]
        KonfluxRD["konflux-release-data (GitLab)"]
        ODHKonflux["odh-konflux-central (GitHub)"]
        ODHOperator["opendatahub-operator (GitHub)"]
        ODHBC["ODH-Build-Config (GitHub)"]
    end

    Wrapper -->|"Fetch YAML"| JiraTicket
    BG -->|"Update labels + comment + status"| JiraTicket
    S2 --> AppInterface
    S3 --> KonfluxRD
    S4 --> ODHKonflux
    S5 --> ODHKonflux
    S6 --> ODHOperator
    S7 --> ODHBC
```

---

## Two Entry Points

### 1. `create-component-onboarding-jira` — Run by Component Teams

This skill is **independent** and intended for component teams, not DevOps. It:

1. Interactively collects onboarding parameters (product context, component name, repo URL, branch, Dockerfile path, whether it is an operator, etc.).
2. Generates a validated `component_onboarding_details.yaml` against a JSON Schema.
3. Attaches the YAML to the Jira ticket (or clones a template Jira and creates a new one for ODH).

```
/create-component-onboarding-jira [<jira-url>]
```

The YAML attachment is the **contract** between the component team and the DevOps automation. Once attached and the Jira label `yaml-attached` is set, the ticket is ready for the wrapper skill.

### 2. `onboard-konflux-components-for-odh-and-rhoai` — Run by DevOps Engineers

This is the **wrapper / parent skill** that drives the full onboarding pipeline. It:

1. Validates prerequisites (env vars, CLI tools).
2. Reads `pipeline_state.json` and resumes from the last completed step if interrupted.
3. Invokes each step skill in sequence, overriding their blocking PR/MR monitors with background monitors.
4. Updates Jira labels and status at each milestone.
5. Transitions the ticket to "Resolved" automatically when all PRs/MRs are merged.

```
/onboard-konflux-components-for-odh-and-rhoai <jira-url>
```

---

## End-to-End Flow

| Step | Skill | Action | Target Repo | HITL Gate |
|------|-------|--------|-------------|-----------|
| 0 | *(wrapper)* | Parse inputs, check prerequisites, init/resume `pipeline_state.json` | — | — |
| 1 | `validate-component-onboarding-jira` | Fetch YAML from Jira; validate against schema; set Jira → "In Progress" | — | Blocks on schema failure |
| 2 | `create-quay-repo` | Raise GitLab MR to `app-interface` to create Quay repository | `gitlab.cee.redhat.com` | MR review + merge |
| 3 | `onboard-component-to-konflux-release-data` | Render Konflux Component YAML; raise GitLab MR to `konflux-release-data`; run `build-single.sh` | `gitlab.cee.redhat.com` | MR review + merge |
| 4 | `add-component-to-odh-konflux-central` | Add Tekton PipelineRun YAMLs (push + PR); update onboarder workflow inputs; raise GitHub PR | `odh-konflux-central` | PR review + merge |
| 5 | `run-odh-konflux-onboarder-workflow` | *(Deferred)* Waits for Steps 2–4 to merge, then triggers `odh-konflux-onboarder.yml` workflow; monitors resulting Tekton PR | `odh-konflux-central` | Tekton PR review + merge |
| 6 | `integrate-component-with-odh-operator` | Skipped if `is_operator=false`. Raise GitHub PR to add manifest config to `opendatahub-operator` | `opendatahub-operator` | PR review + merge |
| 7 | `integrate-component-with-bundle` | Fetch latest image digest from Quay; add `relatedImages` entry to `bundle-patch.yaml`; raise GitHub PR | `ODH-Build-Config` | PR review + merge |

After all PRs/MRs are merged, Jira is transitioned to **Resolved** automatically by the background completion monitor.

---

## Background Monitoring Pattern

The wrapper replaces each step skill's **blocking** PR/MR monitor with a non-blocking background process. This allows the wrapper to raise all PRs/MRs in a single session and then exit, letting monitors run in the background.

- **`launch_monitor.sh`** — starts `monitor_pr.sh` via `nohup`, returns immediately.
- **`monitor_pr.sh`** — polls for merge; on merge, calls `update_jira_issue.py` to post a comment and remove the "raised" label.
- **`deferred_workflow.sh`** — waits for Steps 2, 3, and 4 to merge before triggering the GitHub Actions workflow for Step 5.
- **`monitor_completion.sh`** — polls `pipeline_state.json` until all steps are done, then transitions Jira to "Resolved".

Live event stream (run in a separate terminal while the wrapper is active):
```bash
bash .claude/skills/common/scripts/watch_monitors.sh --workdir ./<JIRA_ID>
```

---

## State Management

The wrapper maintains `<JIRA_ID>/pipeline_state.json` in the working directory. Each step writes its status (`pending` → `mr_raised` / `pr_raised` → `merged` / `skipped`) and the PR/MR URL. On re-invocation with the same Jira URL, completed steps are skipped and the workflow resumes from where it left off.

```json
{
  "jira_url": "...",
  "jira_id": "RHOAIENG-1234",
  "component_name": "my-component",
  "product_context": "ODH",
  "steps": {
    "validate":  { "status": "done" },
    "quay":      { "mr_url": "https://gitlab.../merge_requests/456", "status": "merged" },
    "krd":       { "mr_url": "https://gitlab.../merge_requests/789", "status": "mr_raised" },
    "okc":       { "pr_url": "",  "status": "pending" },
    "onboarder": { "run_id": "", "tekton_pr_url": "", "status": "pending" },
    "operator":  { "pr_url": "",  "status": "skipped" },
    "bundle":    { "pr_url": "",  "status": "pending" }
  }
}
```

---

## Prerequisites

| # | Requirement | Details |
|---|-------------|---------|
| 1 | **Claude Code or Cursor IDE** | Agent mode enabled. |
| 2 | **VPN connected** | Required for GitLab (`gitlab.cee.redhat.com`) and Konflux cluster access (Steps 2, 3). |
| 3 | **Environment variables** | `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`, `GITLAB_USER`, `GITLAB_TOKEN` (api + write_repository), `GITHUB_USER`, `GITHUB_TOKEN` (repo + actions:write). |
| 4 | **CLI tools** | `uv`, `git`, `oc`, `skopeo`, `yamllint`, `jq`, `kustomize`. Run `install.sh` in the wrapper directory to set up any missing shims. |
| 5 | **Skills installed** | Run `install.sh` in each skill directory, or run it from the wrapper directory which installs all dependencies. |
| 6 | **Jira ticket with YAML attached** | Component team must have run `create-component-onboarding-jira` first; the ticket must have the `yaml-attached` label. |

---

## Jira Lifecycle

| Milestone | Jira Status | Labels Added |
|-----------|-------------|-------------|
| YAML attached by component team | *(unchanged)* | `yaml-attached` |
| Wrapper starts, YAML validated | In Progress | — |
| All PRs/MRs raised | Review | `onboarding-in-review` |
| Quay MR merged | Review | `quay-mr-raised` removed |
| KRD MR merged | Review | `konflux-mr-raised` removed |
| OKC PR merged | Review | `okc-pr-raised` removed |
| Tekton PR merged | Review | `tekton-pr-merged` |
| All steps done | Resolved | `onboarding-complete` |

---

## Error Handling and Resumption

| Failure | Recovery |
|---------|----------|
| Missing env var or CLI tool | Wrapper exits with a remediation message at Step 1. Fix and re-run. |
| YAML schema validation fails | `validate-component-onboarding-jira` stops with specific errors. Fix YAML, re-upload to Jira, re-run. |
| VPN drops mid-run | GitLab calls fail. Background monitors retry automatically (60 s intervals). Re-run wrapper for incomplete foreground steps. |
| MR/PR creation fails (3 retries) | Wrapper stops at that step. Check credentials and VPN. Re-run; completed steps are skipped via `pipeline_state.json`. |
| Deferred workflow times out (3 h) | Check `deferred_workflow.log`; re-run `deferred_workflow.sh` manually. |
| Completion monitor times out (4 h) | Check individual `.result` files; re-run `monitor_completion.sh` manually. |
| Re-run after any failure | Re-invoke the wrapper with the same Jira URL. `pipeline_state.json` skips completed steps. |

---

## Planned: Jira-Triggered Automatic Execution

Currently all skills are invoked **manually** by a DevOps engineer in their local Claude Code / Cursor session. The next phase will eliminate this manual step by automatically triggering the wrapper skill when a Jira ticket with `yaml-attached` is created or transitioned.

**Proposed trigger mechanism:**
- A Jira automation rule (or webhook to a CI pipeline) fires when a ticket is created in the RHOAIENG/RHODS project with the `yaml-attached` label.
- The webhook triggers a GitHub Actions workflow (or an ACP/Tekton pipeline) that runs `onboard-konflux-components-for-odh-and-rhoai` in a containerized Claude Code agent session.
- The agent session has all required credentials injected as environment variables from a secrets store.
- All HITL gates (PR review and merge) continue to operate via Jira comments and GitHub/GitLab PR reviews — no human needs to be present in an IDE session.

This mirrors **Approach 1 (Jira-triggered ACP execution)** but uses the same Claude Code skill infrastructure, avoiding duplication. The skills themselves require no changes; only the invocation mechanism changes from manual to automated.

---

## Pros

- **Minimal infrastructure** — no new servers or CI pipelines required for the current phase.
- **Modular and maintainable** — each onboarding step is a separate skill; changes to one step don't affect others.
- **Resumable** — `pipeline_state.json` enables clean recovery from any interruption.
- **Jira as source of truth** — all progress, PR/MR links, and status transitions are recorded in Jira automatically.
- **Non-blocking** — background monitors allow the engineer to raise all PRs/MRs in one session and not wait for each merge manually.
- **Incremental path to automation** — the same skills will be reused when the Jira-triggered phase is implemented.

## Cons

- **Manual invocation** — currently requires a DevOps engineer to start the wrapper skill locally.
- **Local environment dependency** — VPN, credentials, and CLI tools must be set up on every engineer's machine.
- **Context window limits** — very long sessions may truncate earlier context; `pipeline_state.json` mitigates this.
- **Bundle PR requires manual image digest fix** — the SHA placeholder in `bundle-patch.yaml` must be updated once the first Konflux build completes, which may fall outside the automated pipeline.
