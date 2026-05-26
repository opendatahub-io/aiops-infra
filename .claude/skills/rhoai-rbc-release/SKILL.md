---
name: rhoai-rbc-release
description: Create a release branch on GitHub RHOAI-Build-Config with Tekton/bundle/CSV updates and open a pull request
allowed-tools: Bash
user-invocable: true
---

# RHOAI RBC Release

Creates a release branch on GitHub RHOAI-Build-Config by:
- Cloning the repository
- Checking out the previous release branch
- Creating automation branch from previous branch
- Updating Tekton pipeline definitions (renaming and version updates)
- Updating bundle-patch.yaml and csv-patch.yaml
- Committing changes
- Pushing to origin  
- Opening a GitHub Pull Request (or showing changes in dry-run mode)

This is **Step 1** of the RHOAI release onboarding pipeline.

## Prerequisites

- `uv` must be installed and in PATH
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `git` must be installed and in PATH
- `GITHUB_TOKEN` environment variable must be set
  - GitHub personal access token with `repo` scope
  - Set: `export GITHUB_TOKEN=your-token`

Optional environment variables (see rbc_build_config_constants.py for full list):
- `RBC_MAIN_REPO` - GitHub repo URL (default: https://github.com/red-hat-data-services/RHOAI-Build-Config.git)
- `RBC_SKIP_CI` - Set to `0` to not add [skip ci] to commit messages
- `RBC_REBASE_ONTO_LATEST` - Set to `0` to skip rebase before push
- `RBC_SKIP_PROGRESSION_CHECK` - Set to `1` to skip version validation

## Usage

```
/rhoai-rbc-release
/rhoai-rbc-release --dry-run
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 0: Parse inputs and check prerequisites

Ask the user for the following information using AskUserQuestion:

**Question 1 - Previous version:**
> What is the previous version (release branch to base from)?
> Examples: `rhoai-3.4`, `rhoai-3.5-ea.1`

→ Store in `PREVIOUS_VERSION`. Must match format `rhoai-X.Y` or `rhoai-X.Y-ea.N`.

**Question 2 - New version:**
> What is the new version (target release)?
> Examples: `rhoai-3.5`, `rhoai-3.5-ea.2`

→ Store in `NEW_VERSION`. Must match format `rhoai-X.Y` or `rhoai-X.Y-ea.N`.

**Question 3 - Dry-run mode:**
> Should this run in dry-run mode (preview changes without committing)?
> Options: Yes (Recommended), No

→ Store in `DRY_RUN`. Default: `yes`.

**Check prerequisites:**

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "GITHUB_TOKEN" \
  --tools "uv git"
```

On exit 1: display the error and stop. The script provides remediation hints.

---

## Step 1: Run RBC Release

Execute the RBC release automation:

```bash
if [[ "$DRY_RUN" == "yes" ]]; then
  uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_release.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" --dry-run
  RBC_EXIT=$?
else
  uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_release.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION"
  RBC_EXIT=$?
fi
```

**On exit 1:** display stderr and stop with:
```
ERROR in Step 1 (RBC Release): Could not complete release branch creation. See details above. Aborting.
```

**On exit 0 (success):** continue to Step 2.

---

## Step 2: Report results

**If dry-run mode:**

Print:
```
DRY-RUN COMPLETE

Changes have been prepared but NOT committed or pushed.
Working tree: RHOAI-Build-Config/

To review changes:
  cd RHOAI-Build-Config
  git status
  git diff

To commit and create PR manually, run without --dry-run flag.
```

**If NOT dry-run mode:**

Parse the output for the GitHub PR URL (look for pattern `https://github.com/.*/pull/\d+`).

Print:
```
RBC RELEASE COMPLETE

Previous version: <PREVIOUS_VERSION>
New version:      <NEW_VERSION>

GitHub PR: <PR_URL>

The release branch automation branch has been pushed and a pull request created.
Review and merge the PR to proceed with the release onboarding.

Next step: /rhoai-rbc-main <PREVIOUS_VERSION> <NEW_VERSION>
```

If no PR URL found in output, print:
```
RBC RELEASE COMPLETE

Previous version: <PREVIOUS_VERSION>
New version:      <NEW_VERSION>

Changes have been committed and pushed to RHOAI-Build-Config.
Check the repository for the automation branch and PR.

Next step: /rhoai-rbc-main <PREVIOUS_VERSION> <NEW_VERSION>
```

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITHUB_TOKEN` not set | Step 0 | `export GITHUB_TOKEN=your-token` |
| `uv` not installed | Step 0 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `git` not installed | Step 0 | Install via package manager |
| Invalid version format | Step 1 | Use format `rhoai-X.Y` or `rhoai-X.Y-ea.N` |
| Version progression check failed | Step 1 | Ensure new > previous, or set `RBC_SKIP_PROGRESSION_CHECK=1` |
| Branch already exists | Step 1 | Delete conflicting branch or use different version |
| PR creation fails | Step 1 | Check GITHUB_TOKEN has repo scope; verify network |
| Clone fails | Step 1 | Check network, GITHUB_TOKEN, and repo URL |
