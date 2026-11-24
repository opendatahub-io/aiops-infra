# OCP Version Onboarding/Offboarding Automation

Automated tooling for onboarding and offboarding OpenShift Container Platform (OCP) versions across RHOAI releases in the Konflux infrastructure.

## Overview

This automation framework streamlines the multi-step process of adding or removing OCP version support across all active RHOAI releases. It coordinates updates across:

- **RHOAI-Build-Config** release branches (`rhoai-x.y`)
- **RHOAI-Build-Config** main branch (stage builds)
- **Konflux** application and component configurations
- **GitLab** konflux-release-data (ReleasePlan/ReleasePlanAdmission)

## Offboard an OCP version for selected RHOAI releases

```bash
bash run_ocp_onboarding.sh --action offboard \
  --repo-path /path/to/RHOAI-Build-Config \
  --release-data-path /path/to/konflux-release-data \
  --ocp-version 5.06 --rhoai-versions 3.5 \
  --onboarded-range '>=3.6.0 <3.7.0' --dry-run
```

When other releases still use the OCP version, supply the supported range that
should remain after offboarding. The release-data checkout is optional and
enables cleanup of the selected release's stage and production release plans
and admission references. Use `--commit` to record changes locally in both
repositories. Shared Konflux resources are removed only after the workflow
checks that no other catalog, PipelineRun, ReleasePlan, or admission references
the OCP version.


## Directory Structure

```
ocp-onboarding-automation/
├── scripts/                           # Automation scripts
│   ├── parse_ocp_version.sh          # Parse OCP version and export variables
│   ├── detect_ocp_base_image.sh      # Detect base image registry path
│   └── get_supported_rhoai_versions.sh # List active RHOAI versions
├── schemas/                           # JSON Schema validation
│   ├── ocp_onboarding_details.schema.json  # Input validation schema
│   └── ocp_onboarding_example.yaml         # Example configuration
└── lib/                               # Shared libraries (future)
```

## Phase 1 Deliverables ✅ (Completed)

Foundation utilities for OCP version parsing, detection, and RHOAI version discovery.



### 1. `parse_ocp_version.sh`

Parse OCP version strings and export derived variables.

**Usage:**
```bash
eval "$(bash scripts/parse_ocp_version.sh --version "5.0")"
echo "$OCP_BASE_IMAGE"
# Output: registry.redhat.io/openshift5/ose-operator-registry-rhel9:v5.0
```

**Exported Variables:**
- `OCP_VERSION_MAJOR` - Major version (e.g., 5, 4)
- `OCP_VERSION_MINOR` - Minor version (e.g., 0, 19)
- `OCP_VERSION_DOTTED` - Dotted format (e.g., v5.0, v4.19)
- `OCP_VERSION_VAR` - Compact format for filenames (e.g., 50, 419)
- `OCP_VERSION_DASHED` - Dashed format (e.g., 5-0, 4-19)
- `OCP_BASE_IMAGE_REGISTRY` - Registry path (openshift5 or openshift4)
- `OCP_BASE_IMAGE` - Full base image URL

### 2. `detect_ocp_base_image.sh`

Auto-detect and optionally verify the base image for an OCP version.

**Usage:**
```bash
# Just detect
bash scripts/detect_ocp_base_image.sh --version "5.0"

# Detect and verify with skopeo
bash scripts/detect_ocp_base_image.sh --version "5.0" --verify
```

**Key Feature:** Automatically determines the correct registry path (`openshift4` vs `openshift5`) based on major version.

### 3. `get_supported_rhoai_versions.sh`

Query RHOAI-Build-Config repository for all active release branches.

**Usage:**
```bash
# List format (default)
bash scripts/get_supported_rhoai_versions.sh --format list

# JSON array
bash scripts/get_supported_rhoai_versions.sh --format json

# Full branch names
bash scripts/get_supported_rhoai_versions.sh --format branches

# Filter results
bash scripts/get_supported_rhoai_versions.sh --filter "3.6"

# Query remote (requires network)
bash scripts/get_supported_rhoai_versions.sh --remote --format json
```

**Output Formats:**
- `list` - One version per line (e.g., "3.6", "3.5-ea.2")
- `json` - JSON array
- `branches` - Full branch names (e.g., "rhoai-3.6")

### 4. JSON Schema Validation

Defines the structure and validation rules for OCP onboarding/offboarding configuration files.

**Schema:** `schemas/ocp_onboarding_details.schema.json`

**Required Fields:**
- `ocp_version` - OCP version (e.g., "5.0", "4.23")
- `action` - "onboard" or "offboard"
- `rhoai_versions` - Array of RHOAI versions to update

**Optional Fields:**
- `base_image_override` - Custom base image URL
- `jira_issue` - Tracking Jira ID
- `dry_run` - Test mode flag
- `skip_steps` - Steps to skip
- `verify_base_image` - Verify image exists
- `notes` - Free-form documentation

## Phase 2 Deliverables ✅ (Completed)

Release branch automation for updating all RHOAI release branches with new OCP version support.

### 5. `run_step_update_release_branches.sh`

Main orchestrator script that updates all RHOAI release branches.

**Usage:**
```bash
# Dry run for OCP 5.0 onboarding
bash scripts/run_step_update_release_branches.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5,3.4" \
  --dry-run

# Actually onboard with commit
bash scripts/run_step_update_release_branches.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5" \
  --commit

# Onboard and push to remote
bash scripts/run_step_update_release_branches.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6" \
  --push
```

**What it does:**
- For each RHOAI version:
  1. Checkout `rhoai-x.y` branch
  2. Create `catalog/v{ocp}/` directory (copy from latest + update Dockerfile)
  3. Update `config/build-config.yaml` (add to build and release sections)
  4. Commit changes (optional)
  5. Push to remote (optional)

**Features:**
- Supports multiple RHOAI versions in one run
- Idempotent: safe to re-run
- Dry-run mode for testing
- Detailed progress and summary reporting
- macOS/Linux compatible (bash 3.x+)

### 6. `update_catalog_directory.sh`

Create or update catalog/v{ocp}/ directory.

**Usage:**
```bash
bash scripts/update_catalog_directory.sh \
  --catalog-dir /path/to/catalog \
  --ocp-version 5.0 \
  [--dry-run]
```

**What it does:**
- Auto-detects latest existing OCP version as source
- Copies entire directory structure
- Updates Dockerfile FROM line with correct base image
- Preserves all other files (catalog.yaml, etc.)

### 7. `update_build_config.sh`

Update config/build-config.yaml with OCP version.

**Usage:**
```bash
# Onboard
bash scripts/update_build_config.sh \
  --config-file /path/to/build-config.yaml \
  --ocp-version 5.0 \
  --action onboard \
  [--dry-run]

# Offboard
bash scripts/update_build_config.sh \
  --config-file /path/to/build-config.yaml \
  --ocp-version 4.17 \
  --action offboard
```

**What it does:**
- Adds/removes version in `supported-ocp-versions.build` (with base-image)
- Adds/removes version in `supported-ocp-versions.release`
- Uses `yq` for safe YAML manipulation
- Idempotent: detects if already present/absent

### 8. `find_latest_ocp_version.sh`

Find the highest OCP version in a catalog directory.

**Usage:**
```bash
bash scripts/find_latest_ocp_version.sh \
  --catalog-dir /path/to/catalog \
  [--format version|path]
```

**Output:**
- `version` format: `4.22`
- `path` format: `v4.22`

## Testing Results - Phase 2

**Test Scenario:**
```bash
bash scripts/run_step_update_release_branches.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5,3.4" \
  --dry-run
```

**Results:**
```
Total RHOAI versions: 3
Successful:           3
Failed:               0
Skipped:              0

Results by branch:
  rhoai-3.6                 dry-run
  rhoai-3.5                 dry-run
  rhoai-3.4                 dry-run

✓ Release branch updates completed successfully
```

**Example Configuration:**
```yaml
ocp_version: "5.0"
action: onboard
rhoai_versions:
  - "3.6"
  - "3.5"
jira_issue: "RHOAIENG-14002"
verify_base_image: true
notes: "First OCP 5.0 onboarding"
```

## Testing

All Phase 1 scripts have been tested with:
- OCP 5.0 (openshift5 registry)
- OCP 4.22, 4.19 (openshift4 registry)
- All active RHOAI versions (2.8 through 3.6-ea.2)

## Phase 3 Deliverables ✅ (Completed)

Main branch automation for catalog updates, Tekton pipeline generation, and config.yaml management.

### 9. `run_step_update_main_catalog.sh`

Update catalog/rhoai-{version}/v{ocp}/ directories on main branch.

**Usage:**
```bash
# Dry run
bash scripts/run_step_update_main_catalog.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5,3.4" \
  --dry-run

# Actually update with commit
bash scripts/run_step_update_main_catalog.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5" \
  --commit
```

**What it does:**
- Checks out main branch
- For each RHOAI version:
  - Updates `catalog/rhoai-{version}/v{ocp}/` (copy from latest + update Dockerfile)
- Commits and pushes changes (optional)

### 10. `run_step_generate_tekton_pipelines.sh`

Generate Tekton PipelineRun YAML files for each RHOAI version.

**Usage:**
```bash
# Dry run
bash scripts/run_step_generate_tekton_pipelines.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5" \
  --dry-run

# Generate and commit
bash scripts/run_step_generate_tekton_pipelines.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5" \
  --commit
```

**What it does:**
- Generates `.tekton/rhoai-fbc-fragment-rhoai-{version}-ocp-{ocp}-push.yaml` for each RHOAI version
- Uses template-based generation with variable substitution
- Handles pipeline naming, paths, tags, and service accounts

**Generated pipeline example:**
- File: `.tekton/rhoai-fbc-fragment-rhoai-36-ocp-50-push.yaml`
- Component: `rhoai-fbc-fragment-ocp-50`
- Image tag: `ocp-5.0-rhoai-3.6`
- Path: `catalog/rhoai-3.6/v5.0`

### 11. `generate_pipeline_yaml.sh`

The Tekton phase reads the full build version from existing dedicated push PipelineRuns
for the selected RHOAI release line. Use `--build-version` with a single release
line when the manifests are missing or disagree. For a new OCP entry in
`config/new-config.yaml`, pass the supported release range explicitly with
`--onboarded-range`. Onboarding preserves existing targets.

Template-based Tekton pipeline YAML generator (used by run_step_generate_tekton_pipelines.sh).

**Usage:**
```bash
bash scripts/generate_pipeline_yaml.sh \
  --build-version 3.6.0 \
  --rhoai-version 3.6 \
  --ocp-version 5.0 \
  --output-file /path/to/output.yaml
```

**Features:**
- Generates complete PipelineRun YAML
- Variable substitution for versions, paths, tags
- Follows Konflux naming conventions
- Compatible with FBC fragment build pipeline

### 12. `update_config_yaml.sh`

Update config/config.yaml on main branch (similar to build-config.yaml but for main).

**Usage:**
```bash
# Onboard
bash scripts/update_config_yaml.sh \
  --config-file /path/to/config.yaml \
  --ocp-version 5.0 \
  --action onboard

# Offboard
bash scripts/update_config_yaml.sh \
  --config-file /path/to/config.yaml \
  --ocp-version 4.17 \
  --action offboard
```

## Testing Results - Phase 3

**Tekton Pipeline Generation:**
```bash
bash scripts/run_step_generate_tekton_pipelines.sh \
  --ocp-version 5.0 --rhoai-versions "3.6" --dry-run
```

**Results:**
```
Total RHOAI versions: 1
Successful:           1
Failed:               0

Generated: .tekton/rhoai-fbc-fragment-rhoai-36-ocp-50-push.yaml
✓ Tekton pipeline generation completed successfully
```

**Generated YAML validates:**
- ✅ Correct paths: `catalog/rhoai-3.6/v5.0`
- ✅ Correct tags: `ocp-5.0-rhoai-3.6`
- ✅ Correct component: `rhoai-fbc-fragment-ocp-50`
- ✅ Correct service account: `build-pipeline-rhoai-fbc-fragment-ocp-50`
- ✅ CEL expression matches: `catalog/rhoai-3.6/v5.0/rhods-operator/catalog.yaml`

## Master Orchestrator ✅ (Complete)

The `run_ocp_onboarding.sh` script executes all 4 phases in sequence with a single command.

**Usage:**
```bash
# Complete dry run (safe, shows what would happen)
bash run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5,3.4" \
  --dry-run

# Full onboarding (all phases, push to remote)
bash run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5,3.4" \
  --push

# Skip Phase 4 (GitHub only, no VPN needed)
bash run_ocp_onboarding.sh \
  --ocp-version 5.0 \
  --rhoai-versions "3.6,3.5" \
  --skip-phase 4 \
  --push
```

**Features:**
- Executes all 4 phases automatically
- Color-coded progress output
- Detailed summary report with timing
- Interactive error handling
- Prerequisite validation (GitLab credentials for Phase 4)
- Phase skipping support

**Output Summary Example:**
```
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
```

## Next Steps

### Future Enhancements
- Jira integration (auto-create issues, update status)
- Slack notifications
- CI/CD integration (GitHub Actions workflow)
- Offboarding automation (reverse process)
- Auto-detect when new OCP versions are released
- Monitoring dashboard for OCP lifecycle

## References

- **Process Documentation:** `/Users/mchamsed/Downloads/OCP version onboarding_offboarding for RHOAI using Konflux.pdf`
- **RHOAI-Build-Config:** https://github.com/red-hat-data-services/RHOAI-Build-Config
- **Jira Trackers:**
  - RHOAIENG-14002: Automate OCP version onboarding/offboarding
  - RHOAIENG-14001: Create automation to keep supported OCP version list updated

## License

Copyright Red Hat, Inc.
