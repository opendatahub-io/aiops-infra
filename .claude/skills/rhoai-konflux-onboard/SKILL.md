---
name: rhoai-konflux-onboard
description: Update konflux-release-data repository with new RHOAI version and create a GitLab merge request
allowed-tools: Bash
user-invocable: true
---

# RHOAI Konflux Onboard

Updates the konflux-release-data repository for a new RHOAI release by:
- Cloning the konflux-release-data GitLab repository
- Copying version directories (tenant, RPA product/service)
- Updating version numbers in YAML files
- Creating/updating kustomization files
- Running build manifests script
- Creating a branch and pushing changes
- Opening a GitLab Merge Request (or showing changes in dry-run mode)

This is **Step 3** (final step) of the RHOAI release onboarding pipeline.

## Prerequisites

- `uv` must be installed and in PATH
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `git` must be installed and in PATH
- `KONFLUX_REPO_TOKEN` environment variable must be set
  - GitLab personal access token with API scope
  - Set: `export KONFLUX_REPO_TOKEN=your-token`

**Network:** The konflux-release-data repository is on GitLab (gitlab.cee.redhat.com).
**VPN must be active** before running this skill.

Optional environment variables:
- `KONFLUX_RELEASE_DATA_REPO` - GitLab repo URL
- `GITLAB_SSL_VERIFY` - Set to `false` if SSL verification issues occur

## Usage

```
/rhoai-konflux-onboard
/rhoai-konflux-onboard --repo-dir <directory>
/rhoai-konflux-onboard --dry-run
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 0: Parse inputs and check prerequisites

Ask the user for the following information using AskUserQuestion:

**Question 1 - Previous version:**
> What is the previous version (source directory)?
> Examples: `rhoai-3.4`, `rhoai-3.5-ea.1`

→ Store in `PREVIOUS_VERSION`. Must match format `rhoai-X.Y` or `rhoai-X.Y-ea.N`.

**Question 2 - New version:**
> What is the new version (target directory)?
> Examples: `rhoai-3.5`, `rhoai-3.5-ea.2`

→ Store in `NEW_VERSION`. Must match format `rhoai-X.Y` or `rhoai-X.Y-ea.N`.

**Question 3 - Clone directory:**
> What directory should be used for cloning konflux-release-data?
> Default: konflux-release-data

→ Store in `REPO_DIR`. Default: `konflux-release-data`.

**Question 4 - Dry-run mode:**
> Should this run in dry-run mode (preview changes without committing)?
> Options: Yes (Recommended), No

→ Store in `DRY_RUN`. Default: `yes`.

**Check prerequisites:**

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "KONFLUX_REPO_TOKEN" \
  --tools "uv git"
```

On exit 1: display the error and stop.

**VPN check (informational):**

Print:
```
NOTE: This skill requires VPN connection to gitlab.cee.redhat.com
      Ensure VPN is active before proceeding.
```

---

## Step 1: Run Konflux Onboard

Execute the Konflux onboarding automation:

```bash
ONBOARD_ARGS=(
  "$PREVIOUS_VERSION"
  "$NEW_VERSION"
  --repo-dir "$REPO_DIR"
)

if [[ "$DRY_RUN" == "yes" ]]; then
  ONBOARD_ARGS+=(--dry-run)
fi

uv run --script "$COMMON_SCRIPTS_DIR/run_konflux_onboard.py" "${ONBOARD_ARGS[@]}"
KONFLUX_EXIT=$?
```

**On exit 1:** display stderr and stop with:
```
ERROR in Step 1 (Konflux Onboard): Could not complete konflux-release-data update. See details above.

Common issues:
  - VPN not active → Activate Red Hat VPN and retry
  - KONFLUX_REPO_TOKEN invalid → Check token has API scope
  - Repository locked → Wait and retry
  
Aborting.
```

**On exit 0 (success):** continue to Step 2.

---

## Step 2: Report results

**If dry-run mode:**

Print:
```
DRY-RUN COMPLETE

Changes have been prepared but NOT committed or pushed.
Working tree: <REPO_DIR>/

To review changes:
  cd <REPO_DIR>
  git status
  git diff --stat

Modified areas:
  - data/tenant/rhoai/<NEW_VERSION>/ (copied from <PREVIOUS_VERSION>)
  - data/rpa/product/rhoai/<NEW_VERSION>/ (copied from <PREVIOUS_VERSION>)
  - data/rpa/service/rhoai/<NEW_VERSION>/ (copied from <PREVIOUS_VERSION>)
  - Kustomization files updated
  - Version references updated

To commit and create MR manually, run without --dry-run flag.
```

**If NOT dry-run mode:**

Parse the output for the GitLab MR URL.

Print:
```
KONFLUX ONBOARD COMPLETE

Previous version: <PREVIOUS_VERSION>
New version:      <NEW_VERSION>

GitLab MR: <MR_URL>

The konflux-release-data repository has been updated:
  ✓ Tenant directory data/tenant/rhoai/<NEW_VERSION>/ created
  ✓ RPA product directory data/rpa/product/rhoai/<NEW_VERSION>/ created
  ✓ RPA service directory data/rpa/service/rhoai/<NEW_VERSION>/ created
  ✓ Kustomization files updated
  ✓ Version numbers updated
  ✓ Branch pushed to GitLab
  ✓ Merge request created

Review and merge the MR to complete the RHOAI release onboarding pipeline.

🎉 RHOAI RELEASE ONBOARDING PIPELINE COMPLETE! 🎉

All 3 steps finished:
  1. ✓ RBC Release - Release branch created
  2. ✓ RBC Main - Main branch onboarded
  3. ✓ Konflux - konflux-release-data updated

Next: Monitor and merge the PRs/MRs, then test the new release.
```

If no MR URL found:
```
KONFLUX ONBOARD COMPLETE

Changes have been committed and pushed to konflux-release-data.
Check GitLab for the branch and merge request.

🎉 RHOAI RELEASE ONBOARDING PIPELINE COMPLETE!
```

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `KONFLUX_REPO_TOKEN` not set | Step 0 | `export KONFLUX_REPO_TOKEN=your-token` |
| `uv` not installed | Step 0 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| VPN not active | Step 1 | Activate Red Hat VPN |
| SSL verification fails | Step 1 | `export GITLAB_SSL_VERIFY=false` (temporary workaround) |
| Clone fails | Step 1 | Check VPN, token, and network |
| MR creation fails | Step 1 | Check token has API scope for GitLab |
| Directory already exists | Step 1 | Use different `--repo-dir` or remove existing directory |
