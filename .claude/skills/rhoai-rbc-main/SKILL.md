---
name: rhoai-rbc-main
description: Onboard catalog and Tekton files to the main branch of RHOAI-Build-Config (add-only, preserves existing content)
allowed-tools: Bash
user-invocable: true
---

# RHOAI RBC Main Onboard

Onboards a new RHOAI release to the main branch of RHOAI-Build-Config by:
- Copying `catalog/<previous>/` → `catalog/<new>/` (preserves file contents)
- Generating new Tekton pipeline YAML files from templates
- Creating a topic branch on main
- Pushing changes
- Opening a GitHub Pull Request (or showing changes in dry-run mode)

This is **Step 2** of the RHOAI release onboarding pipeline.

**Important:** This is an add-only operation - it does not remove or rename existing files.

## Prerequisites

- `uv` must be installed and in PATH
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `git` must be installed and in PATH
- `GITHUB_TOKEN` environment variable must be set
  - GitHub personal access token with `repo` scope
  - Set: `export GITHUB_TOKEN=your-token`

Optional environment variables:
- `RBC_MAIN_REPO` - GitHub repo URL (default: https://github.com/red-hat-data-services/RHOAI-Build-Config.git)
- `RBC_REPLACE_EXISTING_CATALOG` - Set to `1` to overwrite existing catalog directory
- `RBC_REPLACE_EXISTING_TEKTON` - Set to `1` to overwrite existing Tekton files (useful for EA→GA transitions)
- `RBC_PR_BASE` - PR base branch (default: `main`)

## Usage

```
/rhoai-rbc-main
/rhoai-rbc-main --dry-run
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 0: Parse inputs and check prerequisites

Ask the user for the following information using AskUserQuestion:

**Question 1 - Previous version:**
> What is the previous version (source catalog directory)?
> Examples: `rhoai-3.4`, `rhoai-3.5-ea.1`

→ Store in `PREVIOUS_VERSION`. Must match format `rhoai-X.Y` or `rhoai-X.Y-ea.N`.

**Question 2 - New version:**
> What is the new version (target catalog directory)?
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

On exit 1: display the error and stop.

---

## Step 1: Run RBC Main Onboard

Execute the RBC main branch onboarding:

```bash
if [[ "$DRY_RUN" == "yes" ]]; then
  uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_main.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" --dry-run
  RBC_EXIT=$?
else
  uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_main.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION"
  RBC_EXIT=$?
fi
```

**On exit 1:** Check if the error is about existing catalog directory. If stderr contains "destination already exists: catalog/":

Ask user:
> The catalog directory `catalog/<NEW_VERSION>/` already exists on the main branch.
> Do you want to replace it? (yes / no)

If `yes`: set environment variable and retry:
```bash
export RBC_REPLACE_EXISTING_CATALOG=1
if [[ "$DRY_RUN" == "yes" ]]; then
  uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_main.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" --dry-run
  RBC_EXIT=$?
else
  uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_main.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION"
  RBC_EXIT=$?
fi
```

If still exit 1 or user said `no`: display stderr and stop with:
```
ERROR in Step 1 (RBC Main Onboard): Could not complete main branch onboarding. See details above. Aborting.
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
  git diff --stat

Added:
  - catalog/<NEW_VERSION>/ (copied from <PREVIOUS_VERSION>)
  - New Tekton pipeline YAML files in .tekton/

To commit and create PR manually, run without --dry-run flag.
```

**If NOT dry-run mode:**

Parse the output for the GitHub PR URL.

Print:
```
RBC MAIN ONBOARD COMPLETE

Previous version: <PREVIOUS_VERSION>
New version:      <NEW_VERSION>

GitHub PR: <PR_URL>

The main branch onboarding has been completed:
  ✓ Catalog directory catalog/<NEW_VERSION>/ added
  ✓ Tekton pipeline files generated
  ✓ Topic branch pushed
  ✓ Pull request created

Review and merge the PR to complete main branch onboarding.

Next step: /rhoai-konflux-onboard <PREVIOUS_VERSION> <NEW_VERSION>
```

If no PR URL found:
```
RBC MAIN ONBOARD COMPLETE

Changes have been committed and pushed to RHOAI-Build-Config main branch.
Check the repository for the topic branch and PR.

Next step: /rhoai-konflux-onboard <PREVIOUS_VERSION> <NEW_VERSION>
```

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITHUB_TOKEN` not set | Step 0 | `export GITHUB_TOKEN=your-token` |
| `uv` not installed | Step 0 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Catalog directory already exists | Step 1 | Set `RBC_REPLACE_EXISTING_CATALOG=1` or choose different version |
| Tekton files already exist | Step 1 | Expected for EA→GA; set `RBC_REPLACE_EXISTING_TEKTON=1` to overwrite |
| PR creation fails | Step 1 | Check GITHUB_TOKEN permissions |
| Clone fails | Step 1 | Check network and repo access |
