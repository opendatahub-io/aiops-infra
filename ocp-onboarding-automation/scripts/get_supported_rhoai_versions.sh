#!/usr/bin/env bash
# Get all supported RHOAI versions from RHOAI-Build-Config repository.
# Queries the repository for active release branches (rhoai-x.y and rhoai-x.y-ea.z).
#
# Usage:
#   bash get_supported_rhoai_versions.sh [--repo-path PATH] [--remote] [--format FORMAT]
#
# Options:
#   --repo-path PATH    Path to local RHOAI-Build-Config clone (default: auto-detect)
#   --remote            Query remote branches instead of local (requires network)
#   --format FORMAT     Output format: list (default), json, or branches
#   --filter PATTERN    Filter versions matching pattern (e.g., "3.6" or "ea")
#
# Output formats:
#   list     - One version per line (e.g., "3.6", "3.5-ea.2")
#   json     - JSON array (e.g., ["3.6", "3.5-ea.2"])
#   branches - Full branch names (e.g., "rhoai-3.6", "rhoai-3.5-ea.2")

set -euo pipefail

REPO_PATH=""
USE_REMOTE=false
OUTPUT_FORMAT="list"
FILTER_PATTERN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-path) REPO_PATH="$2"; shift 2 ;;
    --remote)    USE_REMOTE=true; shift ;;
    --format)    OUTPUT_FORMAT="$2"; shift 2 ;;
    --filter)    FILTER_PATTERN="$2"; shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Auto-detect RHOAI-Build-Config repository path
if [[ -z "$REPO_PATH" ]]; then
  # Check common locations
  if [[ -d "/Users/mchamsed/git-workspace/tools/rhoai-onboarding/repos-location/RHOAI-Build-Config" ]]; then
    REPO_PATH="/Users/mchamsed/git-workspace/tools/rhoai-onboarding/repos-location/RHOAI-Build-Config"
  elif [[ -d "$HOME/git-workspace/tools/rhoai-onboarding/repos-location/RHOAI-Build-Config" ]]; then
    REPO_PATH="$HOME/git-workspace/tools/rhoai-onboarding/repos-location/RHOAI-Build-Config"
  elif git rev-parse --git-dir &>/dev/null; then
    # If we're already in a git repo, check if it's RHOAI-Build-Config
    REPO_NAME=$(basename "$(git rev-parse --show-toplevel)")
    if [[ "$REPO_NAME" == "RHOAI-Build-Config" ]]; then
      REPO_PATH="$(git rev-parse --show-toplevel)"
    fi
  fi
fi

# Validate repository path
if [[ -z "$REPO_PATH" && "$USE_REMOTE" == false ]]; then
  echo "ERROR: Could not find RHOAI-Build-Config repository" >&2
  echo "  Use --repo-path to specify the location" >&2
  echo "  Or use --remote to query GitHub directly" >&2
  exit 1
fi

if [[ -n "$REPO_PATH" && ! -d "$REPO_PATH/.git" ]]; then
  echo "ERROR: Not a git repository: $REPO_PATH" >&2
  exit 1
fi

# Get list of branches
if [[ "$USE_REMOTE" == true ]]; then
  # Query remote branches from GitHub
  if [[ -n "$REPO_PATH" ]]; then
    BRANCHES=$(cd "$REPO_PATH" && git ls-remote --heads origin \
      | grep 'refs/heads/rhoai-' \
      | sed -E 's|.*refs/heads/rhoai-([0-9]+\.[0-9]+(-ea\.[0-9]+)?)|\1|' || true)
  else
    # Direct GitHub API query (no authentication needed for public repos)
    BRANCHES=$(curl -s "https://api.github.com/repos/red-hat-data-services/RHOAI-Build-Config/branches?per_page=100" \
      | jq -r '.[].name' \
      | grep '^rhoai-' \
      | sed -E 's|^rhoai-([0-9]+\.[0-9]+(-ea\.[0-9]+)?)|\1|' || true)
  fi
else
  # Query local branches
  BRANCHES=$(cd "$REPO_PATH" && git branch -a \
    | grep -E 'rhoai-[0-9]+\.[0-9]+(-ea\.[0-9]+)?$' \
    | sed -E 's|.*rhoai-([0-9]+\.[0-9]+(-ea\.[0-9]+)?)$|\1|' \
    | sort -u || true)
fi

# Filter branches if pattern provided
if [[ -n "$FILTER_PATTERN" ]]; then
  BRANCHES=$(echo "$BRANCHES" | grep "$FILTER_PATTERN" || true)
fi

# Sort versions (semantic sort)
VERSIONS=$(echo "$BRANCHES" | sort -t. -k1,1n -k2,2n -k3,3n | uniq)

# Check if we got any results
if [[ -z "$VERSIONS" ]]; then
  echo "ERROR: No RHOAI versions found" >&2
  exit 1
fi

# Output in requested format
case "$OUTPUT_FORMAT" in
  list)
    echo "$VERSIONS"
    ;;
  json)
    echo "$VERSIONS" | jq -R . | jq -s .
    ;;
  branches)
    echo "$VERSIONS" | sed 's/^/rhoai-/'
    ;;
  *)
    echo "ERROR: Unknown format: $OUTPUT_FORMAT" >&2
    echo "  Supported formats: list, json, branches" >&2
    exit 1
    ;;
esac
