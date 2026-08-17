# SKILL.md Refactoring - Before vs After

## Before (592 lines of bash)

```markdown
### 3c. Execute step

**For `rbc_release` step:**

```bash
echo "═══════════════════════════════════════════════════════════════"
echo "STEP 1/4: RBC Release"
echo "═══════════════════════════════════════════════════════════════"

# Update Jira to in_progress
JIRA_TASK=$(jq -r '.jira.child_tasks.rbc_release' "$STATE_FILE")
if [[ "$JIRA_TASK" != "null" && "$JIRA_TASK" != "DRY-RUN" ]]; then
  uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$JIRA_TASK" \
    --status "In Progress" >/dev/null 2>&1 || true
fi

if [[ "$DRY_RUN" == "yes" ]]; then
  OUTPUT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_release.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" --dry-run 2>&1)
  STEP_EXIT=$?
else
  OUTPUT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_rbc_release.py" \
    "$PREVIOUS_VERSION" "$NEW_VERSION" 2>&1)
  STEP_EXIT=$?
fi

echo "$OUTPUT"

if [[ $STEP_EXIT -eq 0 ]]; then
  PR_URL=$(echo "$OUTPUT" | grep -oP 'https://github\.com/[^/]+/[^/]+/pull/\d+' | head -1)
  jq ".steps.rbc_release.status = \"done\" | \
      .steps.rbc_release.pr_url = \"${PR_URL:-N/A}\" | \
      .steps.rbc_release.completed_at = \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" \
    "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  echo "✓ RBC Release completed"
  
  # Update Jira child task
  JIRA_TASK=$(jq -r '.jira.child_tasks.rbc_release' "$STATE_FILE")
  if [[ "$JIRA_TASK" != "null" && -n "$PR_URL" ]]; then
    echo "Updating Jira task $JIRA_TASK..."
    uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$JIRA_TASK" \
      --pr-url "$PR_URL" --status "Resolved" 2>&1 | grep -E "^(✓|⚠|ERROR)" || true
  fi
else
  jq ".steps.rbc_release.status = \"failed\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
  echo "✗ RBC Release failed (exit $STEP_EXIT)"
  
  # Update Jira child task to failed
  JIRA_TASK=$(jq -r '.jira.child_tasks.rbc_release' "$STATE_FILE")
  if [[ "$JIRA_TASK" != "null" ]]; then
    uv run --script "$COMMON_SCRIPTS_DIR/rhoai_release_jira.py" update "$JIRA_TASK" \
      --status "Failed" 2>&1 | grep -E "^(✓|⚠|ERROR)" || true
  fi
  exit 1
fi
```

**For `rbc_main` step:**
... (another 50 lines of similar bash)

**For `konflux` step:**
... (another 50 lines of similar bash)

**For `pipelinerun_replicator` step:**
... (another 50 lines of similar bash)
```

**Problems:**
- 592 lines of complex bash
- Logic duplicated 4 times (one per step)
- Hard to test
- Hard to maintain
- Error-prone (bash string manipulation, state updates)
- No clear separation of concerns

---

## After (133 lines, just invocation)

```markdown
## Step 3: Execute the pipeline

Build and execute the command:

```bash
CMD="uv run --script $COMMON_SCRIPTS_DIR/run_y_stream_pipeline.py $PREVIOUS_VERSION $NEW_VERSION"

# Add optional arguments
if [[ "$REPO_DIR" != "konflux-release-data" ]]; then
  CMD="$CMD --repo-dir $REPO_DIR"
fi

if [[ "$DRY_RUN" == "yes" ]]; then
  CMD="$CMD --dry-run"
fi

# Execute
$CMD
```

That's it! The Python script handles:
- Prerequisites checking
- Jira creation/retrieval
- State management
- Step execution with dependency tracking
- Jira status updates (In Progress → Resolved/Failed)
- Final summary and cleanup
- Automatic resume on re-run
```

**Benefits:**
- 78% reduction in SKILL.md size (592 → 133 lines)
- All logic in testable Python script
- Single source of truth
- No code duplication
- Easy to extend and maintain
- Clear separation: SKILL.md = interface, script = implementation

---

## Python Script Structure

```python
# run_y_stream_pipeline.py (504 lines)

def check_prerequisites() -> bool:
    """Check tools and env vars"""
    
def create_or_get_jira() -> dict:
    """Create/retrieve Jira tracking"""
    
def initialize_state() -> Path:
    """Create/load state file"""
    
def execute_step(step_name: str) -> bool:
    """
    Execute one step:
    1. Check if already done
    2. Check dependencies
    3. Mark as in_progress (state + Jira)
    4. Run the script
    5. Parse output for PR/MR URL
    6. Mark as done/failed (state + Jira)
    """
    
def finalize_pipeline():
    """Update parent Jira, show summary, cleanup"""
    
def main():
    """Orchestrate the full pipeline"""
```

**Key Features:**
1. **Idempotent** - Can run multiple times, resumes automatically
2. **State tracking** - JSON file tracks each step's status
3. **Dependency checking** - Won't run step 2 until step 1 is done
4. **Jira integration** - Auto-updates throughout pipeline
5. **Clean output** - Colored, formatted terminal output
6. **Error handling** - Graceful failures with clear messages

---

## Example: Step Execution Logic

### Before (in SKILL.md, bash):
```bash
# 30+ lines of bash per step
if [[ $STEP_EXIT -eq 0 ]]; then
  PR_URL=$(echo "$OUTPUT" | grep -oP 'https://github\.com/[^/]+/[^/]+/pull/\d+' | head -1)
  jq ".steps.rbc_release.status = \"done\" | ...
  # ... more bash string manipulation
fi
```

### After (in Python script):
```python
# Shared logic for all steps
url_match = re.search(config["url_pattern"], output)
url = url_match.group(0) if url_match else "N/A"

if exit_code == 0:
    state["steps"][step_name]["status"] = "done"
    state["steps"][step_name][url_key] = url
    state["steps"][step_name]["completed_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state_file, state)
    update_jira_status(jira_key, "Resolved", url)
```

**Benefits:**
- Single implementation for all steps
- Type-safe (Python vs bash strings)
- Easier to test and debug
- Better error messages
- Proper date handling

---

## Migration Impact

✅ **No breaking changes**
- Skill works exactly the same from user perspective
- Can resume existing pipelines
- State files are compatible

✅ **Better user experience**
- Clearer output with colors
- Better error messages
- Shows progress more clearly

✅ **Better developer experience**
- Much easier to modify
- Easier to add new steps
- Easier to test
- Fewer bugs

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| SKILL.md lines | 592 | 133 |
| Code in SKILL.md | Bash (complex) | Bash (simple invocation) |
| Logic location | Scattered in SKILL.md | Centralized in Python |
| Code duplication | 4x (one per step) | None (shared logic) |
| Testability | Hard (bash) | Easy (Python) |
| Maintainability | Low | High |
| Idempotency | Manual | Automatic |
| State management | Manual (jq + bash) | Automatic (Python + JSON) |
| Error handling | Basic | Comprehensive |
| Output formatting | Plain text | Colored + formatted |

**Result:** Same functionality, much better implementation following senior's feedback to remove bash from skills and make it idempotent.
