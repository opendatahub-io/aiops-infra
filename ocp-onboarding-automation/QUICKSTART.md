# OCP Onboarding - Quick Start Guide

## TL;DR - One Command to Rule Them All

```bash
cd /Users/mchamsed/git-workspace/tools/aiops-infra/ocp-onboarding-automation

# Onboard OCP 5.0 for RHOAI 3.6, 3.5, and 3.4
bash run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5,3.4" \
  --push
```

That's it! ✨ The automation will:
1. ✅ Update all RHOAI release branches (rhoai-3.6, rhoai-3.5, rhoai-3.4)
2. ✅ Update main branch catalogs
3. ✅ Generate Tekton PipelineRun YAMLs
4. ✅ Create Konflux Application and Components (requires VPN)

## Before You Run

### 1. Ensure you're in RHOAI-Build-Config repository

```bash
cd /path/to/RHOAI-Build-Config
```

### 2. Test with dry-run first (recommended)

```bash
bash /path/to/ocp-onboarding-automation/run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6" \
  --dry-run
```

This shows exactly what would happen without making any changes.

### 3. For Phase 4 (Konflux) - Set GitLab credentials

```bash
export GITLAB_USER="your-username"
export GITLAB_TOKEN="your-personal-access-token"
```

**Note:** Phase 4 requires VPN connection to `gitlab.cee.redhat.com`

### 4. Skip Phase 4 if VPN not available

```bash
bash run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5,3.4" \
  --skip-phase 4 \
  --push
```

## Common Use Cases

### Onboard a new OCP version across all active RHOAI versions

```bash
# Get all active RHOAI versions
RHOAI_VERSIONS=$(bash scripts/get_supported_rhoai_versions.sh --filter "3." --format list | tr '\n' ',' | sed 's/,$//')

# Onboard
bash run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "$RHOAI_VERSIONS" \
  --push
```

### Onboard for a single RHOAI version (testing)

```bash
bash run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6" \
  --push
```

### Run only specific phases

```bash
# Phases 1-3 only (GitHub operations, no VPN)
bash run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5" \
  --skip-phase 4 \
  --push

# Phase 4 only (requires previous phases completed)
bash scripts/run_step_create_konflux_app.sh \
  --ocp-version 5.0
```

### Commit locally without pushing

```bash
bash run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6" \
  --commit
```

Review commits, then push manually:
```bash
git push origin rhoai-3.6
git push origin main
```

## Output Example

```
============================================
  OCP Version Onboarding - Master Script  
============================================

OCP Version:       5.0
Base Image:        registry.redhat.io/openshift5/ose-operator-registry-rhel9:v5.0
RHOAI Versions:    3 (3.6,3.5,3.4)
Mode:              push

============================================

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1: Update RHOAI Release Branches
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
...
✓ Phase 1 completed successfully

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 2: Update Main Branch Catalogs
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
...
✓ Phase 2 completed successfully

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 3: Generate Tekton PipelineRuns
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
...
✓ Phase 3 completed successfully

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 4: Create Konflux Application
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
...
✓ Phase 4 completed successfully

════════════════════════════════════════
         ONBOARDING SUMMARY             
════════════════════════════════════════

OCP Version:       5.0
RHOAI Versions:    3 (3.6,3.5,3.4)
Mode:              push
Duration:          8m 23s

Phase Results:
  ✓ Phase 1: Update RHOAI Release Branches
  ✓ Phase 2: Update Main Branch Catalogs
  ✓ Phase 3: Generate Tekton PipelineRuns
  ✓ Phase 4: Create Konflux Application

════════════════════════════════════════
✓ All phases completed successfully!

OCP 5.0 has been onboarded for:
  - RHOAI 3.6
  - RHOAI 3.5
  - RHOAI 3.4
```

## Getting Help

```bash
# Show all options
bash run_ocp_onboarding.sh --help

# Individual script help
bash scripts/run_step_update_release_branches.sh --help
bash scripts/run_step_update_main_catalog.sh --help
bash scripts/run_step_generate_tekton_pipelines.sh --help
bash scripts/run_step_create_konflux_app.sh --help
```

## What Gets Changed

The automation makes changes to these repositories:

### RHOAI-Build-Config (GitHub)

**Release Branches (rhoai-x.y):**
- `catalog/v5.0/` - New OCP catalog directory (copied from latest)
- `catalog/v5.0/Dockerfile` - Updated with OCP 5.0 base image
- `config/build-config.yaml` - Added v5.0 to build and release sections

**Main Branch:**
- `catalog/rhoai-3.6/v5.0/` - New catalog per RHOAI version
- `catalog/rhoai-3.5/v5.0/` - (and so on...)
- `.tekton/rhoai-fbc-fragment-rhoai-36-ocp-50-push.yaml` - New pipelines
- `config/config.yaml` - Updated with v5.0

### konflux-release-data (GitLab - Phase 4 only)

- `tenants/rhoai/applications/ocp-50.yaml` - New Konflux Application/Component
- `tenants/rhoai/applications/kustomization.yaml` - Updated resources list

## Troubleshooting

### "Could not resolve host: gitlab.cee.redhat.com"

**Solution:** Connect to Red Hat VPN or skip Phase 4:
```bash
bash run_ocp_onboarding.sh ... --skip-phase 4
```

### "GITLAB_USER environment variable not set"

**Solution:** Export GitLab credentials:
```bash
export GITLAB_USER="your-username"
export GITLAB_TOKEN="your-token"
```

### "Catalog directory not found: catalog/rhoai-X.Y"

**Cause:** Main branch doesn't have this RHOAI version's catalog yet.

**Solution:** This is expected for older RHOAI versions. The script skips these automatically.

### Phase fails mid-execution

**Solution:** The automation is idempotent - safe to re-run:
```bash
bash run_ocp_onboarding.sh ... --push
```

It will skip already-completed work and continue from where it failed.

## Advanced Usage

### Find all scripts

```bash
cd /path/to/ocp-onboarding-automation
find scripts -name "*.sh" -type f | sort
```

### Run individual phases manually

```bash
# Phase 1 only
bash scripts/run_step_update_release_branches.sh \
  --ocp-version 5.0 --rhoai-versions "3.6" --push

# Phase 2 only
bash scripts/run_step_update_main_catalog.sh \
  --ocp-version 5.0 --rhoai-versions "3.6" --push

# Phase 3 only
bash scripts/run_step_generate_tekton_pipelines.sh \
  --ocp-version 5.0 --rhoai-versions "3.6" --push

# Phase 4 only
bash scripts/run_step_create_konflux_app.sh \
  --ocp-version 5.0
```

### Test with multiple RHOAI versions

```bash
# Start small
bash run_ocp_onboarding.sh --ocp-version 5.0 --rhoai-versions "3.6" --dry-run

# Scale up
bash run_ocp_onboarding.sh --ocp-version 5.0 --rhoai-versions "3.6,3.5" --dry-run

# Full scale
bash run_ocp_onboarding.sh --ocp-version 5.0 --rhoai-versions "3.6,3.5,3.4,3.3" --dry-run
```

## Documentation

- **README.md** - Full technical documentation
- **IMPLEMENTATION_SUMMARY.md** - Complete implementation details and metrics
- **QUICKSTART.md** - This file
- **schemas/ocp_onboarding_details.schema.json** - JSON Schema for validation

## Next Steps After Onboarding

1. **Verify PipelineRuns** - Check that Tekton pipelines trigger correctly
2. **Monitor Builds** - Watch Konflux for successful builds
3. **Update Jira** - Mark onboarding issue as complete
4. **Announce** - Notify team that new OCP version is supported

## Time Savings

| Task | Manual Time | Automated Time | Savings |
|------|-------------|----------------|---------|
| 1 RHOAI version | 1-2 hours | 2-3 minutes | ~95% |
| 3 RHOAI versions | 4-6 hours | 5-10 minutes | ~90% |
| All active versions | 8-12 hours | 10-15 minutes | ~95% |

**Plus:** Near-zero error rate with automation vs. high manual error risk!
