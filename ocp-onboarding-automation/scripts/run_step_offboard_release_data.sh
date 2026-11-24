#!/usr/bin/env bash
# Remove the selected pair's ReleasePlans and admission application references.
set -euo pipefail

REPO_PATH=$1
OCP_VERSION=$2
RHOAI_VERSIONS=$3
MODE=$4
BUILD_CONSUMERS=${5:-true}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
parsed=$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")
eval "$parsed"
cd "$REPO_PATH"
if [[ "$MODE" == --push ]]; then
  echo "ERROR: Release-data offboarding supports dry-run and local commits. Review the release-data commit before pushing." >&2
  exit 1
fi
if [[ "$MODE" == --commit && -n "$(git status --porcelain)" ]]; then
  echo "ERROR: Use a clean release-data checkout" >&2
  exit 1
fi
export OFFBOARD_APP="rhoai-fbc-fragment-ocp-$OCP_VERSION_VAR"
source_dir=tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant
generated_dir=tenants-config/auto-generated/cluster/stone-prod-p02/tenants/rhoai-tenant
if [[ ! -d "$source_dir" || ! -d "$generated_dir" ]]; then
  echo "ERROR: Expected RHOAI tenant directories in release-data checkout" >&2
  exit 1
fi
IFS=',' read -ra releases <<< "$RHOAI_VERSIONS"
changed=()
planned_plans=()
planned_admissions=()
for release in "${releases[@]}"; do
  release="${release#rhoai-}"
  if [[ ! "$release" =~ ^[0-9]+[.][0-9]+(-ea[.][0-9]+)?$ ]]; then
    echo "ERROR: Invalid RHOAI release line: $release" >&2
    exit 1
  fi
  slug="${release//./-}"
  for environment in Prod Stage; do
    env=$(printf '%s' "$environment" | tr '[:upper:]' '[:lower:]')
    export OFFBOARD_PLAN="rhoai-onprem-v$slug-ocp-$OCP_VERSION_VAR-fbc-$env"
    source="$source_dir/v$release/${environment}ReleasePlans-v$release.yaml"
    generated="$generated_dir/appstudio.redhat.com_v1alpha1_releaseplan_$OFFBOARD_PLAN.yaml"
    plan='.kind == "ReleasePlan" and .metadata.name == strenv(OFFBOARD_PLAN) and .spec.application == strenv(OFFBOARD_APP)'
    if [[ -f "$source" && "$(yq "select($plan) | .metadata.name" "$source")" == "$OFFBOARD_PLAN" ]]; then
      planned_plans+=("$source:$OFFBOARD_PLAN")
      echo "Remove $OFFBOARD_PLAN from $source"
      if [[ "$MODE" == --commit ]]; then
        yq -i "select(($plan) | not)" "$source"
        changed+=("$source")
      fi
    fi
    if [[ -f "$generated" && "$(yq "select($plan) | .metadata.name" "$generated")" == "$OFFBOARD_PLAN" ]]; then
      planned_plans+=("$generated:$OFFBOARD_PLAN")
      echo "Remove $generated"
      if [[ "$MODE" == --commit ]]; then
        git rm -- "$generated"
        changed+=("$generated")
      fi
    fi
    for admission in config/*/product/ReleasePlanAdmission/rhoai/"rhoai-onprem-v$slug-fbc-$env.yaml"; do
      [[ -f "$admission" ]] || continue
      match=$(yq '.spec.applications[] | select(. == strenv(OFFBOARD_APP))' "$admission")
      [[ -n "$match" ]] || continue
      planned_admissions+=("$admission")
      echo "Remove $OFFBOARD_APP from $admission"
      if [[ "$MODE" == --commit ]]; then
        yq -i 'del(.spec.applications[] | select(. == strenv(OFFBOARD_APP)))' "$admission"
        changed+=("$admission")
      fi
    done
  done
done
# Inspect the remaining references across the release-data checkout. In preview
# mode, subtract the exact references above that the operation would remove.
release_data_consumers=false
if [[ "$BUILD_CONSUMERS" == false ]]; then
  grep_status=0
  candidates=$(git grep -l -F "$OFFBOARD_APP" -- '*.yaml' '*.yml') || grep_status=$?
  if [[ "$grep_status" -gt 1 ]]; then
    exit "$grep_status"
  fi
  while IFS= read -r path; do
    [[ -n "$path" && -f "$path" ]] || continue
    plans=$(yq -r 'select(.kind == "ReleasePlan" and .spec.application == strenv(OFFBOARD_APP)) | .metadata.name' "$path")
    while IFS= read -r name; do
      [[ -n "$name" ]] || continue
      for planned in ${planned_plans[@]+"${planned_plans[@]}"}; do
        [[ "$planned" != "$path:$name" ]] || continue 2
      done
      release_data_consumers=true
    done <<< "$plans"
    admissions=$(yq -r '.spec.applications[] | select(. == strenv(OFFBOARD_APP))' "$path")
    if [[ -n "$admissions" ]]; then
      for planned in ${planned_admissions[@]+"${planned_admissions[@]}"}; do
        [[ "$planned" != "$path" ]] || continue 2
      done
      release_data_consumers=true
    fi
  done <<< "$candidates"
fi

if [[ "$BUILD_CONSUMERS" == true || "$release_data_consumers" == true ]]; then
  echo "Preserve shared Konflux resources for $OCP_VERSION_DOTTED because a consumer remains or RHOAI-Build-Config was not checked."
else
  export SHARED_FILE="ocp-$OCP_VERSION_VAR.yaml"
  for directory in "$source_dir/fbc-fragments" tenants/rhoai/applications; do
    kustomization="$directory/kustomization.yaml"
    if [[ -f "$kustomization" ]]; then
      resource=$(yq -r '.resources[] | select(. == strenv(SHARED_FILE))' "$kustomization")
      if [[ -n "$resource" ]]; then
        echo "Remove $SHARED_FILE from $kustomization"
        if [[ "$MODE" == --commit ]]; then
          yq -i 'del(.resources[] | select(. == strenv(SHARED_FILE)))' "$kustomization"
          changed+=("$kustomization")
        fi
      fi
    fi
  done
  for manifest in \
    "$source_dir/fbc-fragments/$SHARED_FILE" \
    "tenants/rhoai/applications/$SHARED_FILE" \
    "$generated_dir/projctl.konflux.dev_v1beta1_projectdevelopmentstream_$OFFBOARD_APP.yaml" \
    "$generated_dir/projctl.konflux.dev_v1beta1_projectdevelopmentstreamtemplate_$OFFBOARD_APP.yaml" \
    "$generated_dir/appstudio.redhat.com_v1alpha1_application_$OFFBOARD_APP.yaml" \
    "$generated_dir/appstudio.redhat.com_v1alpha1_component_$OFFBOARD_APP.yaml"; do
    [[ -f "$manifest" ]] || continue
    echo "Remove $manifest"
    if [[ "$MODE" == --commit ]]; then
      git rm -- "$manifest"
      changed+=("$manifest")
    fi
  done
fi

if [[ -n "${changed[0]:-}" ]]; then
  git commit -m "Offboard OCP $OCP_VERSION_FULL release data for $RHOAI_VERSIONS" -- "${changed[@]}"
fi
