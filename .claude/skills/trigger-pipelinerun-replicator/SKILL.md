# Trigger PipelineRun Replicator

Trigger the pipelinerun-replicator GitHub Actions workflow in konflux-central to replicate PipelineRun configurations between RHOAI releases

## Prerequisites

- `uv` must be installed and in PATH
- `GITHUB_TOKEN` — GitHub personal access token with workflow permissions

## Usage

```
/trigger-pipelinerun-replicator
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 1: Ask for versions

Ask the user using AskUserQuestion:

**Question 1 - Source version:**
> What is the source RHOAI version to replicate from?
> Examples: `rhoai-3.5-ea.2`, `rhoai-3.5-ea.6`

→ Store in `SOURCE_VERSION`.

**Question 2 - Target version:**
> What is the target RHOAI version to replicate to?
> Examples: `rhoai-3.5-ea.3`, `rhoai-3.5-ea.7`

→ Store in `TARGET_VERSION`.

**Question 3 - Dry-run mode:**
> Should this run in dry-run mode?
> Note: Dry-run will preview the workflow trigger without actually triggering it.
> Options: Yes, No (Recommended for production)

→ Store in `DRY_RUN`. Default: `no`.

---

## Step 2: Trigger the workflow

Display:
```
═══════════════════════════════════════════════════════════════
Triggering PipelineRun Replicator Workflow
═══════════════════════════════════════════════════════════════
Source version: <SOURCE_VERSION>
Target version: <TARGET_VERSION>
Dry-run mode:   <DRY_RUN>
```

Run the workflow trigger script:

```bash
if [[ "$DRY_RUN" == "yes" ]]; then
  uv run --script "$COMMON_SCRIPTS_DIR/run_pipelinerun_replicator.py" \
    "$SOURCE_VERSION" "$TARGET_VERSION" --dry-run
else
  uv run --script "$COMMON_SCRIPTS_DIR/run_pipelinerun_replicator.py" \
    "$SOURCE_VERSION" "$TARGET_VERSION"
fi
```

---

## Step 3: Display results

If successful, display:

```
✓ PipelineRun Replicator workflow triggered

Workflow Run: <RUN_URL>

Next steps:
  1. Monitor the workflow run
  2. Verify PipelineRuns were replicated correctly
  3. Check for any failures or warnings
```

If failed, display the error and exit.

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITHUB_TOKEN` not set | Step 2 | `export GITHUB_TOKEN=your-token` |
| Workflow trigger fails | Step 2 | Check token has `workflow` permissions |
| Cannot find workflow run | Step 2 | Check GitHub Actions manually |
