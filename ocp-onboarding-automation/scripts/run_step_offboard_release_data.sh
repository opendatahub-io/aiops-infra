#!/usr/bin/env bash
# Remove the selected pair's ReleasePlans and admission application references.
set -euo pipefail

REPO_PATH=$1
OCP_VERSION=$2
RHOAI_VERSIONS=$3
MODE=$4
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
      echo "Remove $OFFBOARD_PLAN from $source"
      if [[ "$MODE" == --commit ]]; then
        yq -i "select(($plan) | not)" "$source"
        changed+=("$source")
      fi
    fi
    if [[ -f "$generated" && "$(yq "select($plan) | .metadata.name" "$generated")" == "$OFFBOARD_PLAN" ]]; then
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
      echo "Remove $OFFBOARD_APP from $admission"
      if [[ "$MODE" == --commit ]]; then
        yq -i 'del(.spec.applications[] | select(. == strenv(OFFBOARD_APP)))' "$admission"
        changed+=("$admission")
      fi
    done
  done
done
if [[ -n "${changed[0]:-}" ]]; then
  git commit -m "Offboard OCP $OCP_VERSION_FULL release plans for $RHOAI_VERSIONS" -- "${changed[@]}"
fi
