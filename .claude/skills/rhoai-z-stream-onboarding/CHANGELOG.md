# RHOAI Z-Stream Onboarding - Change Log

## Version 3.0 - GitHub Actions Integration (2026-06-02)

### ✨ New Features

#### 1. **Fourth Pipeline Step: Apply Z-Stream Changes**
- Added GitHub Actions workflow trigger as step 4
- Triggers `apply-z-stream-changes.yml` workflow in konflux-central
- Automatically extracts target branch and RHOAI version from input
- Monitors workflow run and returns URL for tracking

#### 2. **Simplified SKILL.md Implementation**
- Removed Jira handling from SKILL.md (now handled by Python script)
- Follows Y-stream pattern for consistency
- Cleaner, more maintainable skill definition

#### 3. **Enhanced Jira Integration**
- Jira now creates 4 child tasks (added Apply Z-Stream Changes)
- Automatic workflow run URL tracking in Jira
- Status updates for GitHub Actions workflow execution

### 📋 Pipeline Steps (Updated)

The complete 4-step pipeline:

1. **RBC Release** — Update release branch on RHOAI-Build-Config
2. **RBC Main** — Update main branch Tekton fragments
3. **Konflux** — Update konflux-release-data
4. **Apply Z-Stream Changes** — Trigger GitHub Actions workflow in konflux-central

### 📁 Files Added/Modified

```
.claude/skills/common/scripts/
├── run_apply_z_stream_changes.py    # NEW - GitHub Actions trigger
├── rhoai_zstream_jira.py            # UPDATED - 4 child tasks
└── run_z_stream_pipeline.py         # UPDATED - 4-step pipeline

.claude/skills/rhoai-z-stream-onboarding/
├── SKILL.md                         # UPDATED - Simplified
└── CHANGELOG.md                     # UPDATED - This file
```

### 🔧 GitHub Actions Workflow Parameters

The `apply-z-stream-changes.yml` workflow receives:
- **target_branch**: Extracted from new version (e.g., `3.4.2` → `rhoai-3.4`)
- **rhoai_version**: Version without prefix (e.g., `rhoai-3.4.2` → `3.4.2`)

### 🎯 Updated Jira Structure

**Parent Issue:**
```
RHOAIENG-XXXXX: RHOAI Z-Stream Release: {previous} → {new}
```

**4 Child Sub-tasks:**
1. `RHOAIENG-YYYYY`: RBC Z-Stream Release
2. `RHOAIENG-ZZZZZ`: RBC Z-Stream Main
3. `RHOAIENG-WWWWW`: Konflux Z-Stream
4. `RHOAIENG-VVVVV`: Apply Z-Stream Changes ← **NEW**

### 📊 Updated State File Structure

```json
{
  "steps": {
    "rbc_release": {"status": "done", "pr_url": "..."},
    "rbc_main": {"status": "done", "pr_url": "..."},
    "konflux": {"status": "done", "mr_url": "..."},
    "apply_z_stream_changes": {"status": "done", "run_url": "..."}
  }
}
```

### 🆚 Comparison: Y-Stream vs Z-Stream (Updated)

| Feature | Y-Stream | Z-Stream |
|---------|----------|----------|
| Pipeline Steps | 4 (RBC Release, RBC Main, Konflux, PipelineRun Replicator) | 4 (RBC Release, RBC Main, Konflux, Apply Z-Stream Changes) |
| Step 4 Workflow | pipelinerun-replicator.yml | apply-z-stream-changes.yml |
| Jira Children | 4 sub-tasks | 4 sub-tasks |
| Version Type | Minor releases (rhoai-3.4 → rhoai-3.5) | Patch releases (3.4.1 → 3.4.2) |

---

## Version 2.0 - Jira Integration (2026-06-02)

### ✨ New Features

#### 1. **Full Jira Integration**
- Added `rhoai_zstream_jira.py` script for Jira management
- Automatic Jira parent issue creation with 4 child sub-tasks
- Real-time Jira status updates (Pending → In Progress → Resolved)
- PR/MR URLs automatically added as comments to Jira tasks

#### 2. **Flexible Jira Options**
The skill now asks users for their Jira preference:
- **Create new Jira** (Recommended) - Automatically creates parent + 4 child tasks
- **Use existing Jira** - Provide existing Jira URL to use for tracking

#### 3. **Enhanced Pipeline Orchestrator**
- Support for `--jira-url <URL>` to use existing Jira
- Support for `--no-jira` to skip Jira integration entirely
- Automatic venv Python detection for proper dependency resolution
- Improved error handling for Jira operations

### 📋 Jira Structure

When creating a new Jira, the system automatically generates:

**Parent Issue:**
```
RHOAIENG-XXXXX: RHOAI Z-Stream Release: {previous} → {new}
```

**4 Child Sub-tasks:**
1. `RHOAIENG-YYYYY`: RBC Z-Stream Release
2. `RHOAIENG-ZZZZZ`: RBC Z-Stream Main
3. `RHOAIENG-WWWWW`: Konflux Z-Stream
4. `RHOAIENG-VVVVV`: Apply Z-Stream Changes

### 🔄 Status Automation

Each child task automatically:
1. Starts in **To Do** state
2. Transitions to **In Progress** when step begins
3. Gets PR/MR URL added as comment when step completes
4. Transitions to **Resolved** when step succeeds
5. Transitions to **Failed** if step fails

The parent issue receives a final summary comment when all steps complete.

### 📁 Files Added/Modified

```
.claude/skills/common/scripts/
├── rhoai_zstream_jira.py        # NEW - Jira management
└── run_z_stream_pipeline.py     # ENHANCED - Jira integration

.claude/skills/rhoai-z-stream-onboarding/
├── SKILL.md                      # UPDATED - Jira question flow
├── README.md                     # Existing
└── CHANGELOG.md                  # NEW - This file
```

### 🎯 Usage Examples

#### Example 1: Create New Jira (Recommended)
```bash
/rhoai-z-stream-onboarding
# Select: "No - Create new Jira (Recommended)"
# Enter versions: 3.4.1 → 3.4.2
# Result: Creates RHOAIENG-12345 with 4 child tasks
```

#### Example 2: Use Existing Jira
```bash
/rhoai-z-stream-onboarding
# Select: "Yes - I have existing Jira URL"
# Enter URL: https://redhat.atlassian.net/browse/RHOAIENG-12345
# Enter versions: 3.4.1 → 3.4.2
# Result: Uses existing Jira for tracking
```

#### Example 3: Direct Script Usage
```bash
# Create new Jira
uv run .claude/skills/common/scripts/run_z_stream_pipeline.py 3.4.1 3.4.2

# Use existing Jira
uv run .claude/skills/common/scripts/run_z_stream_pipeline.py 3.4.1 3.4.2 \
  --jira-url https://redhat.atlassian.net/browse/RHOAIENG-12345

# Skip Jira
uv run .claude/skills/common/scripts/run_z_stream_pipeline.py 3.4.1 3.4.2 --no-jira

# Dry-run mode
uv run .claude/skills/common/scripts/run_z_stream_pipeline.py 3.4.1 3.4.2 --dry-run
```

### 🔧 CLI Arguments

```
run_z_stream_pipeline.py [-h] [--repo-dir REPO_DIR] [--dry-run] 
                         [--resume STATE_FILE] [--jira-url URL] [--no-jira]
                         [previous_version] [new_version]

Arguments:
  previous_version     Previous z-stream version (e.g., 3.4.1, 3.4.0-ea.1)
  new_version          New z-stream version (e.g., 3.4.2, 3.4.1-ea.1)

Options:
  --repo-dir DIR       Konflux-release-data clone directory (default: konflux-release-data)
  --dry-run            Preview changes without creating PRs/MRs
  --resume STATE_FILE  Resume from existing state file
  --jira-url URL       Use existing Jira issue for tracking
  --no-jira            Skip Jira integration entirely
```

### 🆚 Comparison: Y-Stream vs Z-Stream

| Feature | Y-Stream | Z-Stream |
|---------|----------|----------|
| Pipeline Steps | 4 (RBC Release, RBC Main, Konflux, PipelineRun Replicator) | 4 (RBC Release, RBC Main, Konflux, Apply Z-Stream Changes) |
| Jira Parent | RHOAI Release Onboarding | RHOAI Z-Stream Release |
| Jira Children | 4 sub-tasks | 4 sub-tasks |
| Version Type | Minor releases (3.4 → 3.5) | Patch releases (3.4.1 → 3.4.2) |
| Jira Options | Auto-create or existing | Auto-create, existing, or skip |
| State File | `rhoai-release-{version}-state.json` | `rhoai-zstream-{version}-state.json` |
| Jira State File | `rhoai-release-{version}-jira.json` | `rhoai-zstream-{version}-jira.json` |

### 📊 State Files

The pipeline maintains two state files:

**1. Pipeline State** (`rhoai-zstream-{version}-state.json`)
```json
{
  "release_info": {...},
  "jira": {
    "parent_key": "RHOAIENG-12345",
    "child_tasks": {...}
  },
  "steps": {
    "rbc_release": {"status": "done", "pr_url": "..."},
    "rbc_main": {"status": "done", "pr_url": "..."},
    "konflux": {"status": "done", "mr_url": "..."},
    "apply_z_stream_changes": {"status": "done", "run_url": "..."}
  }
}
```

**2. Jira State** (`rhoai-zstream-{version}-jira.json`)
```json
{
  "parent_issue": {
    "key": "RHOAIENG-12345",
    "url": "https://redhat.atlassian.net/browse/RHOAIENG-12345"
  },
  "child_tasks": {
    "rbc_release": {"key": "RHOAIENG-12346", "url": "..."},
    "rbc_main": {"key": "RHOAIENG-12347", "url": "..."},
    "konflux": {"key": "RHOAIENG-12348", "url": "..."},
    "apply_z_stream_changes": {"key": "RHOAIENG-12349", "url": "..."}
  }
}
```

### 🔐 Environment Variables

```bash
# Required for Jira integration
export JIRA_TOKEN="your-jira-api-token"
export JIRA_EMAIL="your-email@redhat.com"  # For Atlassian Cloud

# Optional Jira configuration
export JIRA_URL="https://redhat.atlassian.net"  # Default
export JIRA_PROJECT="RHOAIENG"  # Default

# Required for pipeline
export GITHUB_TOKEN="your-github-token"
export KONFLUX_REPO_TOKEN="your-gitlab-token"
```

### ⚠️ Breaking Changes

None - this is a backward-compatible enhancement. Existing usage without Jira still works:
```bash
uv run .claude/skills/common/scripts/run_z_stream_pipeline.py 3.4.1 3.4.2 --no-jira
```

### 🐛 Bug Fixes

- Fixed venv Python detection for proper dependency resolution
- Fixed module import errors by using venv Python from rhoai-release-onboarding

### 📚 Documentation Updates

- Updated SKILL.md with Jira question flow
- Updated README.md with Jira integration details
- Added this CHANGELOG.md

---

## Version 1.0 - Initial Release (2026-06-02)

### ✨ Initial Features

- 4-step z-stream pipeline orchestration
- State tracking and idempotent execution
- Dry-run mode support
- Resume capability from state files
- Integration with rhoai-release-onboarding Python scripts

### 📁 Initial Files

```
.claude/skills/common/scripts/
└── run_z_stream_pipeline.py

.claude/skills/rhoai-z-stream-onboarding/
├── SKILL.md
└── README.md
```

### 🎯 Initial Usage

```bash
/rhoai-z-stream-onboarding
# Enter versions and options
```
