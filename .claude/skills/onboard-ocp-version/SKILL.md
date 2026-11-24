---
name: onboard-ocp-version
description: Onboard a new OpenShift Container Platform (OCP) version across all active RHOAI releases. Automates catalog updates, Tekton pipeline generation, and Konflux application creation. Runs all 4 phases automatically or individually with --skip-phase.
allowed-tools: Bash
user-invocable: true
---

# Onboard OCP Version

Automates the complete OCP version onboarding process across all RHOAI releases.

Replaces the manual 15+ step process with a single command, reducing time from 4-6 hours to 5-10 minutes with near-zero error rate.

## What It Does

**Phase 1:** Update RHOAI release branches (rhoai-x.y)
- Create `catalog/v{ocp}/` directory (copy from latest OCP version)
- Update Dockerfile with new OCP base image
- Update `config/build-config.yaml`

**Phase 2:** Update main branch catalogs
- Create `catalog/rhoai-{version}/v{ocp}/` for each RHOAI version
- Copy and update Dockerfiles
- Update `config/config.yaml`

**Phase 3:** Generate Tekton PipelineRuns
- Generate `.tekton/rhoai-fbc-fragment-rhoai-{version}-ocp-{ocp}-push.yaml` for each RHOAI version
- Configure CEL expressions, paths, and image tags

**Phase 4:** Create Konflux Application (requires VPN)
- Clone `gitlab.cee.redhat.com/releng/konflux-release-data`
- Generate `tenants/rhoai/applications/ocp-{version}.yaml`
- Update `kustomization.yaml`
- Create GitLab Merge Request

## Usage

```bash
# Full onboarding (all phases)
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6,3.5,3.4" --push

# Dry run (safe, shows what would happen)
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6" --dry-run

# Skip Phase 4 (GitHub only, no VPN needed)
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6,3.5" --skip-phase 4 --push

# Commit locally without pushing
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6" --commit
```

## Arguments

**Required:**
- `--ocp-version VERSION` - OCP version to onboard (e.g., 5.0, 4.23)
- `--rhoai-versions LIST` - Comma-separated RHOAI versions (e.g., "3.6,3.5,3.4")

**Optional:**
- `--dry-run` - Show what would be done (default, safe)
- `--commit` - Make commits but don't push
- `--push` - Make commits and push to remote
- `--skip-phase N[,N...]` - Skip specific phases (1-4)
- `--onboarded-range RANGE` - Release range for a new OCP entry in `config/new-config.yaml`
- `--build-version VER` - Full Tekton build version override for one release line
- `--repo-path PATH` - Path to the RHOAI-Build-Config checkout

## Prerequisites

**GitHub (Phases 1-3):**
- Repository: RHOAI-Build-Config cloned locally
- Current directory must be in RHOAI-Build-Config
- Git authentication configured

**GitLab (Phase 4 only):**
- Environment: `GITLAB_USER`, `GITLAB_TOKEN` (api + write_repository scope)
- VPN connection to `gitlab.cee.redhat.com` active
- Repository: konflux-release-data (auto-cloned)

**Tools:**
- git, bash, yq, sed, grep, find

## Examples

### Onboard OCP 5.0 for all active RHOAI 3.x versions

```bash
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6,3.5,3.4,3.3" --push
```

### Test with single RHOAI version first

```bash
# Dry run
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6" --dry-run

# Execute
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6" --push
```

### Phases 1-3 only (no GitLab/VPN)

```bash
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6,3.5,3.4" --skip-phase 4 --push
```

### Run Phase 4 separately (after Phases 1-3)

```bash
# Phases 1-3 first
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6,3.5" --skip-phase 4 --push

# Phase 4 later (when VPN available)
bash $OCP_ONBOARDING_DIR/scripts/run_step_create_konflux_app.sh --ocp-version 5.0
```

## Implementation

### Locate Scripts Directory

```bash
# OCP_ONBOARDING_DIR is set via exports or defaults to aiops-infra location
OCP_ONBOARDING_DIR="${OCP_ONBOARDING_DIR:-${AIOPS_INFRA_DIR}/ocp-onboarding-automation}"

if [[ ! -d "$OCP_ONBOARDING_DIR" ]]; then
  echo "ERROR: OCP onboarding directory not found at $OCP_ONBOARDING_DIR"
  echo "  Set OCP_ONBOARDING_DIR or AIOPS_INFRA_DIR environment variable."
  exit 1
fi

MASTER_SCRIPT="$OCP_ONBOARDING_DIR/run_ocp_onboarding.sh"
if [[ ! -x "$MASTER_SCRIPT" ]]; then
  echo "ERROR: Master orchestrator not found at $MASTER_SCRIPT"
  exit 1
fi

echo "Using OCP onboarding automation from: $OCP_ONBOARDING_DIR"
```

### Parse Arguments

Extract `--ocp-version`, `--rhoai-versions`, and mode flags from the skill invocation arguments.

```bash
# Parse arguments from skill invocation
OCP_VERSION=""
RHOAI_VERSIONS=""
MODE_FLAGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ocp-version)
      OCP_VERSION="$2"
      shift 2
      ;;
    --rhoai-versions)
      RHOAI_VERSIONS="$2"
      shift 2
      ;;
    --dry-run|--commit|--push)
      MODE_FLAGS+=("$1")
      shift
      ;;
    --skip-phase|--onboarded-range|--build-version|--repo-path)
      MODE_FLAGS+=("$1" "$2")
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      shift
      ;;
  esac
done

# Validate required arguments
if [[ -z "$OCP_VERSION" ]]; then
  echo "ERROR: --ocp-version is required"
  echo "Usage: /onboard-ocp-version --ocp-version 5.0 --rhoai-versions \"3.6,3.5\" [--push]"
  exit 1
fi

if [[ -z "$RHOAI_VERSIONS" ]]; then
  echo "ERROR: --rhoai-versions is required"
  echo "Usage: /onboard-ocp-version --ocp-version 5.0 --rhoai-versions \"3.6,3.5\" [--push]"
  exit 1
fi

# Default to dry-run if no mode specified
if [[ ${#MODE_FLAGS[@]} -eq 0 ]]; then
  MODE_FLAGS=("--dry-run")
fi

echo "OCP Version: $OCP_VERSION"
echo "RHOAI Versions: $RHOAI_VERSIONS"
echo "Flags: ${MODE_FLAGS[*]}"
```

### Verify Working Directory

The automation requires being run from within the RHOAI-Build-Config repository.

```bash
# Check if we're in RHOAI-Build-Config
if [[ ! -d ".git" ]] || ! git remote -v | grep -q "RHOAI-Build-Config"; then
  echo "ERROR: Must be run from RHOAI-Build-Config repository"
  echo "Current directory: $(pwd)"
  echo ""
  echo "Please navigate to RHOAI-Build-Config and try again:"
  echo "  cd /path/to/RHOAI-Build-Config"
  echo "  /onboard-ocp-version --ocp-version $OCP_VERSION --rhoai-versions \"$RHOAI_VERSIONS\""
  exit 1
fi

echo "Repository: $(git remote get-url origin)"
```

### Execute Master Orchestrator

Run the master orchestrator script with all parsed arguments.

```bash
# Execute the master orchestrator
echo ""
echo "Running OCP onboarding automation..."
echo ""

bash "$MASTER_SCRIPT" \
  --ocp-version "$OCP_VERSION" \
  --rhoai-versions "$RHOAI_VERSIONS" \
  "${MODE_FLAGS[@]}"

EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  echo ""
  echo "✓ OCP onboarding completed successfully!"
else
  echo ""
  echo "✗ OCP onboarding failed with exit code $EXIT_CODE"
  exit $EXIT_CODE
fi
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

## Troubleshooting

### VPN Connection Issues

**Symptom:** Phase 4 fails with "Could not resolve host: gitlab.cee.redhat.com"

**Solution:** 
- Connect to Red Hat VPN, OR
- Skip Phase 4: `/onboard-ocp-version ... --skip-phase 4 --push`

### Not in RHOAI-Build-Config Repository

**Symptom:** "ERROR: Must be run from RHOAI-Build-Config repository"

**Solution:** Navigate to the repository first:
```bash
cd /path/to/RHOAI-Build-Config
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6"
```

### GitLab Credentials Not Set

**Symptom:** Phase 4 fails with "GITLAB_USER environment variable not set"

**Solution:** Export credentials before running:
```bash
export GITLAB_USER="your-username"
export GITLAB_TOKEN="your-personal-access-token"
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6" --push
```

### Phase Fails Mid-Execution

**Solution:** The automation is idempotent - safe to re-run:
```bash
/onboard-ocp-version --ocp-version 5.0 --rhoai-versions "3.6" --push
```

It will skip already-completed work and continue from where it failed.

## Time Savings

| Scope | Manual Time | Automated Time | Savings |
|-------|-------------|----------------|---------|
| 1 RHOAI version | 1-2 hours | 2-3 minutes | ~95% |
| 3 RHOAI versions | 4-6 hours | 5-10 minutes | ~90% |
| All active versions | 8-12 hours | 10-15 minutes | ~95% |

**Plus:** Near-zero error rate vs. high manual error risk!

## Related Documentation

- **QUICKSTART.md** - Quick reference guide
- **README.md** - Complete technical documentation
- **IMPLEMENTATION_SUMMARY.md** - Implementation details and metrics
- **Manual process PDF** - Original 15-step manual procedure (now automated)

## Notes

- All phases are idempotent - safe to re-run multiple times
- Dry-run is the default mode for safety
- Phase 4 can be skipped if VPN is not available
- The automation handles OCP 4.x (openshift4 registry) and OCP 5.x (openshift5 registry) automatically
- ReleasePlan updates (Step 8 from manual process) are placeholder - requires konflux-release-data structure analysis
