#!/usr/bin/env bash
# Remove the selected OCP/RHOAI catalogs and dedicated PipelineRuns from main.
set -euo pipefail

REPO_PATH=""
OCP_VERSION=""
RHOAI_VERSIONS=""
ONBOARDED_RANGE=""
MODE=dry-run
CHECK_CONSUMERS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-path|--ocp-version|--rhoai-versions|--onboarded-range)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "ERROR: $1 requires a value" >&2
        exit 1
      fi
      case "$1" in
        --repo-path) REPO_PATH="$2" ;;
        --ocp-version) OCP_VERSION="$2" ;;
        --rhoai-versions) RHOAI_VERSIONS="$2" ;;
        --onboarded-range) ONBOARDED_RANGE="$2" ;;
      esac
      shift 2
      ;;
    --check-consumers) CHECK_CONSUMERS=true; shift ;;
    --dry-run|--commit|--push) MODE="${1#--}"; shift ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$REPO_PATH" || -z "$OCP_VERSION" || -z "$RHOAI_VERSIONS" ]]; then
  echo "ERROR: Offboarding requires --repo-path, --ocp-version, and --rhoai-versions" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
parsed=$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")
eval "$parsed"
cd "$REPO_PATH"

IFS=',' read -ra RELEASES <<< "$RHOAI_VERSIONS"
TARGETS=()
for release in "${RELEASES[@]}"; do
  release="${release#rhoai-}"
  if [[ ! "$release" =~ ^[0-9]+[.][0-9]+(-ea[.][0-9]+)?$ ]]; then
    echo "ERROR: Invalid RHOAI release line: $release" >&2
    exit 1
  fi
  TARGETS+=("catalog/rhoai-$release/$OCP_VERSION_DOTTED")
  TARGETS+=(".tekton/rhoai-fbc-fragment-rhoai-${release//./}-ocp-$OCP_VERSION_VAR-push.yaml")
done

if [[ "$MODE" != dry-run ]]; then
  git checkout main
  if git rev-parse --verify '@{upstream}' >/dev/null 2>&1; then
    git pull --ff-only
  fi
fi

# Read the tracked main tree even when the dry-run starts on a release branch.
tree=$(git ls-tree -r --name-only main -- catalog .tekton)
REMOVE=()
REMAINING=false
HAS_CATALOG=false
while IFS= read -r path; do
  [[ -n "$path" ]] || continue
  if [[ "$path" == catalog/rhoai-*/"$OCP_VERSION_DOTTED/"* ]]; then
    HAS_CATALOG=true
  fi
  for target in "${TARGETS[@]}"; do
    if [[ "$path" == "$target" || "$path" == "$target/"* ]]; then
      REMOVE+=("$path")
      continue 2
    fi
  done
  if [[ "$path" == catalog/rhoai-*/"$OCP_VERSION_DOTTED/"* ||
        "$path" == .tekton/rhoai-fbc-fragment-rhoai-*-ocp-"$OCP_VERSION_VAR"-push.yaml ]]; then
    REMAINING=true
  fi
done <<< "$tree"

# A release branch may be onboarded before its artifacts reach main.
refs=$(git for-each-ref --format='%(refname)' 'refs/heads/rhoai-*' 'refs/remotes/origin/rhoai-*')
while IFS= read -r ref; do
  [[ -n "$ref" ]] || continue
  for release in "${RELEASES[@]}"; do
    if [[ "${ref##*/}" == "rhoai-${release#rhoai-}" ]]; then
      continue 2
    fi
  done
  if [[ "$ref" == refs/remotes/origin/* ]] &&
     git merge-base --is-ancestor "$ref" "refs/heads/${ref##*/}" 2>/dev/null; then
    # A local offboarding commit can be ahead of the cached remote branch.
    continue
  fi
  if git cat-file -e "$ref:catalog/$OCP_VERSION_DOTTED" 2>/dev/null; then
    REMAINING=true
    break
  fi
done <<< "$refs"

if [[ "$CHECK_CONSUMERS" == true ]]; then
  printf '%s\n' "$REMAINING"
  exit 0
fi

CONFIG=config/new-config.yaml
CONFIG_CHANGE=""
if git cat-file -e "main:$CONFIG" 2>/dev/null; then
  config=$(git show "main:$CONFIG")
  old_range=$(OCP_TARGET="$OCP_VERSION_DOTTED" yq -r \
    '.config."supported-ocp-versions"[] | select(.version == strenv(OCP_TARGET)) | .["onboarded-range"]' - <<< "$config")
  if [[ -n "$old_range" ]]; then
    if [[ "$REMAINING" == true ]]; then
      if [[ -n "${REMOVE[0]:-}" && -z "$ONBOARDED_RANGE" ]]; then
        echo "ERROR: Other releases still use $OCP_VERSION_DOTTED. Supply their remaining --onboarded-range." >&2
        exit 1
      fi
      if [[ -n "${REMOVE[0]:-}" && -n "$ONBOARDED_RANGE" && "$ONBOARDED_RANGE" != "$old_range" ]]; then
        CONFIG_CHANGE=range
      fi
    elif [[ "$HAS_CATALOG" == true && -n "${REMOVE[0]:-}" ]]; then
      CONFIG_CHANGE=remove
    fi
  fi
fi

if [[ -n "${REMOVE[0]:-}" ]]; then
  printf 'Remove %s\n' "${REMOVE[@]}"
fi
case "$CONFIG_CHANGE" in
  range) echo "Set $OCP_VERSION_DOTTED onboarded-range to $ONBOARDED_RANGE in $CONFIG" ;;
  remove) echo "Remove the $OCP_VERSION_DOTTED entry from $CONFIG" ;;
esac

if [[ "$REMAINING" == true ]]; then
  echo "Preserve shared Konflux resources for $OCP_VERSION_DOTTED. Other RHOAI releases still use them."
else
  echo "Check release-data references before removing shared Konflux resources."
fi

if [[ "$MODE" == dry-run ]]; then
  exit 0
fi

if [[ -n "$CONFIG_CHANGE" ]] && ! git diff --quiet HEAD -- "$CONFIG"; then
  echo "ERROR: Commit or restore local changes to $CONFIG before offboarding." >&2
  exit 1
fi

if [[ -n "${REMOVE[0]:-}" ]]; then
  git rm -- "${REMOVE[@]}"
fi
case "$CONFIG_CHANGE" in
  range)
    OCP_TARGET="$OCP_VERSION_DOTTED" RELEASE_RANGE="$ONBOARDED_RANGE" yq -i \
      '(.config."supported-ocp-versions"[] | select(.version == strenv(OCP_TARGET)) | .["onboarded-range"]) = strenv(RELEASE_RANGE)' "$CONFIG"
    ;;
  remove)
    OCP_TARGET="$OCP_VERSION_DOTTED" yq -i \
      'del(.config."supported-ocp-versions"[] | select(.version == strenv(OCP_TARGET)))' "$CONFIG"
    ;;
esac
if [[ -n "$CONFIG_CHANGE" ]]; then
  REMOVE+=("$CONFIG")
fi
if [[ -n "${REMOVE[0]:-}" ]]; then
  git commit -m "Offboard OCP $OCP_VERSION_FULL for $RHOAI_VERSIONS" -- "${REMOVE[@]}"
fi
if [[ "$MODE" == push ]]; then
  git push origin main
fi
