# Offboarding Konflux components (how to use)

The offboarding pipeline is **manual and idempotent**. You (or an agent) invoke the
skills locally; there is no scheduled CI job yet. Re-run the orchestrator any number
of times for the same Jira — it syncs PR/MR state, executes newly-unblocked steps,
and posts a Jira comment only when something changed.

Skill-by-skill change notes: [create](create-component-offboarding-jira.md),
[validate](validate-component-offboarding-jira.md),
[orchestrator](offboard-konflux-components-for-odh-and-rhoai.md).
Pipeline table: [index](index.md#offboarding-pipeline).

## 1. Install the skills

From a checkout of this repo:

```bash
# One-time: CLI deps (uv, jq, oc, skopeo, yamllint, kustomize, …)
bash .claude/skills/install-dependencies.sh

# Symlink skills into ~/.claude/skills/ so Claude Code can invoke them
bash .claude/skills/install.sh --force

export AIOPS_INFRA_DIR="$(pwd)"
```

Restart Claude Code after installing. The three offboarding skills are:

| Skill | When to use |
|-------|-------------|
| `/create-component-offboarding-jira` | Collect parameters, write YAML, create/update the Jira |
| `/validate-component-offboarding-jira <jira-url>` | Pre-flight check (also run automatically by the orchestrator) |
| `/offboard-konflux-components-for-odh-and-rhoai <jira-url>` | Run / resume the full pipeline |

## 2. Credentials and tools

Export these before running (same variables as onboarding):

```bash
export JIRA_USER_EMAIL='you@redhat.com'
export JIRA_API_TOKEN='...'          # https://id.atlassian.com/manage-profile/security/api-tokens
export GITHUB_USER='your-github-user'
export GITHUB_TOKEN='...'            # repo scope
export GITLAB_USER='your-gitlab-user'
export GITLAB_TOKEN='...'            # api + write_repository (GitLab.cee)
```

**VPN must be on** — GitLab at `gitlab.cee.redhat.com` is required for the KRD step.
The skill checks VPN itself; do not treat SSL failures against that host as “VPN down”.

**OpenShift login** is prompted interactively (`oc login --web`) if you do not already
have a session:

| Product | Cluster |
|---------|---------|
| RHOAI | internal — `api.stone-prod-p02.hjvn.p1.openshiftapps.com` |
| ODH | external — `api.stone-prd-rh01.pg1f.p1.openshiftapps.com` |

Tools: `uv`, `git`, `oc`, `skopeo`, `yamllint`, `jq`, `kustomize` (or `kubectl`).

## 3. Create the offboarding Jira

```
/create-component-offboarding-jira
```

or attach YAML to an existing ticket:

```
/create-component-offboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234
```

The skill asks for:

- **product** — `ODH` or `RHOAI`
- **ODH:** build type (`CI` / `Release`) · **RHOAI:** target version (`3.4`, `3.4-ea-2`, …)
- **component name** — must start with `odh-`
- **GitHub repo URL**
- **operator?** — yes/no
- **parent feature** Jira ID (linked as “relates to”)

With no URL it clones template [`RHOAIENG-32534`](https://redhat.atlassian.net/browse/RHOAIENG-32534),
attaches `component_offboarding_details.yaml`, and labels the ticket
`offboarding-yaml-attached`.

## 4. Run the orchestrator

```
/offboard-konflux-components-for-odh-and-rhoai https://redhat.atlassian.net/browse/RHOAIENG-1234
```

It validates the YAML, raises independent removal PRs/MRs in parallel, then the
dependent cleanup steps. After reviewers merge those PRs/MRs, **re-run the same
command** — the next unblocked steps execute.

Jira moves `In Progress` → `Review` (while PRs are open) → `Resolved` when everything
is done (`component-offboarding-completed` label).

## Pipeline steps

| Step | What it removes | Where | Notes |
|------|-----------------|-------|-------|
| `remove_krd` | Component from ProductDataSet / RPA / automation | `konflux-release-data` GitLab MR | VPN required |
| `remove_okc` | Push PipelineRun | ODH or RHOAI Konflux Central GitHub PR | |
| `remove_pull_pipelines` | Pull-request PipelineRun | RHOAI Konflux Central GitHub PR | RHOAI only (skipped for ODH) |
| `remove_bundle` | relatedImages, build-config, Dockerfile ARGs/labels, `bundle_build_args.map` | ODH/RHOAI Build-Config GitHub PR | |
| `remove_operator` | Operator manifests | odh-operator / rhods-operator GitHub PR | Only if `is_operator: true` |
| `sync_component_tekton` | Stale `.tekton/` PipelineRun files | Component repo GitHub PR(s) | After OKC / pull-pipeline PRs merge |
| `remove_component_cr` | Konflux `Component` CR | OpenShift cluster | **Asks for confirmation.** Annotates ImageRepository with `skip-repository-deletion=true` so Quay images are kept |

The orchestrator does **not** delete Quay repositories or RHOAI product-listing
entries. Those are shared / version-spanning and must be cleaned up separately if
needed.

## Dry run

End-to-end test without merging or deleting cluster objects:

```bash
export OFFBOARD_DRY_RUN=true
```

PRs/MRs get a `[DRY RUN]` title, Jira comments are prefixed `[DRY RUN]`, and
Component CR deletion is skipped (it prints what it would do). Close the dry-run
PRs/MRs and delete their branches when you are done.

## Component CR confirmation

The last step is destructive. The first run prints the Component(s) and
ImageRepository object(s) it would change and **waits for you to confirm**. A
second run with `--confirm` performs the `oc` deletes. Quay image repos are
preserved via the ImageRepository annotation.
