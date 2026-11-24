#!/usr/bin/env bash
# Add a new OCP FBC ReleasePlan to each selected release's stage and prod configuration.
set -euo pipefail

OCP_VERSION=""
RHOAI_VERSIONS=""
KRD_REPO_PATH=""
DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ocp-version|--rhoai-versions|--krd-repo-path)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "ERROR: $1 requires a value" >&2
        exit 1
      fi
      case "$1" in
        --ocp-version) OCP_VERSION="$2" ;;
        --rhoai-versions) RHOAI_VERSIONS="$2" ;;
        --krd-repo-path) KRD_REPO_PATH="$2" ;;
      esac
      shift 2
      ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$OCP_VERSION" || -z "$RHOAI_VERSIONS" || -z "$KRD_REPO_PATH" ]]; then
  echo "ERROR: --ocp-version, --rhoai-versions, and --krd-repo-path are required" >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
parsed=$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")
eval "$parsed"
cd "$KRD_REPO_PATH"

source_dir=tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant
generated_dir=tenants-config/auto-generated/cluster/stone-prod-p02/tenants/rhoai-tenant
admission_dir=config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai
export TARGET_APP="rhoai-fbc-fragment-ocp-$OCP_VERSION_VAR"

# Render all changes into a temporary directory before touching the checkout.
preview=$(mktemp -d)
trap 'rm -rf -- "$preview"' EXIT

stage_file() {
  local path=$1
  mkdir -p "$preview/$(dirname "$path")"
}

IFS=',' read -ra releases <<< "$RHOAI_VERSIONS"
for release in "${releases[@]}"; do
  release="${release#rhoai-}"
  if [[ ! "$release" =~ ^[0-9]+[.][0-9]+(-ea[.][0-9]+)?$ ]]; then
    echo "ERROR: Invalid RHOAI release line: $release" >&2
    exit 1
  fi
  slug="${release//./-}"
  for environment in prod stage; do
    case "$environment" in prod) title=Prod ;; stage) title=Stage ;; esac
    export ADMISSION_NAME="rhoai-onprem-v$slug-fbc-$environment"
    export TARGET_PLAN="rhoai-onprem-v$slug-ocp-$OCP_VERSION_VAR-fbc-$environment"
    source="$source_dir/v$release/${title}ReleasePlans-v$release.yaml"
    admission="$admission_dir/$ADMISSION_NAME.yaml"
    generated="$generated_dir/appstudio.redhat.com_v1alpha1_releaseplan_$TARGET_PLAN.yaml"

    if [[ ! -f "$source" || ! -f "$admission" || ! -d "$generated_dir" ]]; then
      echo "ERROR: Missing $environment ReleasePlan or admission configuration for RHOAI $release" >&2
      exit 1
    fi

    manifest=$(yq 'select(.kind == "ReleasePlan" and .metadata.name == strenv(TARGET_PLAN))' "$source")
    if [[ -z "$manifest" ]]; then
      manifest=$(yq eval-all '
        [select(.kind == "ReleasePlan" and
                (.spec.application // "" | test("^rhoai-fbc-fragment-ocp-[0-9]+$")) and
                .metadata.labels."release.appstudio.openshift.io/releasePlanAdmission" == strenv(ADMISSION_NAME))] |
        .[-1] | select(. != null) |
        .metadata.name = strenv(TARGET_PLAN) |
        .spec.application = strenv(TARGET_APP)
      ' "$source")
      if [[ -z "$manifest" ]]; then
        echo "ERROR: No $environment FBC ReleasePlan template for RHOAI $release" >&2
        exit 1
      fi
      stage_file "$source"
      { cat "$source"; printf '\n---\n%s\n' "$manifest"; } > "$preview/$source"
    fi

    if [[ "$(printf '%s\n' "$manifest" | yq -r '.spec.application' -)" != "$TARGET_APP" ]]; then
      echo "ERROR: $TARGET_PLAN already exists with a different application" >&2
      exit 1
    fi

    if [[ ! -e "$generated" && ! -L "$generated" ]]; then
      stage_file "$generated"
      printf '%s\n' "$manifest" > "$preview/$generated"
    fi

    existing=$(yq '.spec.applications[] | select(. == strenv(TARGET_APP))' "$admission")
    if [[ -z "$existing" ]]; then
      stage_file "$admission"
      yq '.spec.applications += [strenv(TARGET_APP)]' "$admission" > "$preview/$admission"
    fi
  done
done

while IFS= read -r -d '' file; do
  path="${file#"$preview/"}"
  if [[ "$DRY_RUN" == true ]]; then
    printf 'Would update %s\n' "$path"
  else
    cp "$file" "$path"
    printf 'Updated %s\n' "$path"
  fi
done < <(find "$preview" -type f -print0)
