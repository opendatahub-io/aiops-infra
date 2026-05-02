---
name: onboard-component-to-konflux-release-data
description: Onboards a new ODH/RHOAI component onto the Konflux CI platform by raising a merge request to the konflux-release-data GitLab repo. Automates Step 3 of the ODH component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Onboard Component to Konflux Release Data

Creates Konflux `Component` resources for a new ODH/RHOAI component by appending a YAML
document to the appropriate tenant config file in the `konflux-release-data` GitLab repository
and raising a merge request. When the MR is merged, a GitOps pipeline provisions the Component
on the Konflux OpenShift cluster.

## Usage

```
/onboard-component-to-konflux-release-data <jira-url>
```

Examples:
```
/onboard-component-to-konflux-release-data https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Prerequisites

- `GITLAB_USER` — your GitLab username (`export GITLAB_USER=yourusername`)
- `GITLAB_TOKEN` — GitLab personal access token with `api` + `write_repository` scopes
- `JIRA_USER_EMAIL` — your Atlassian account email
- `JIRA_API_TOKEN` — Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens)
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `oc` — OpenShift CLI (https://console.redhat.com/openshift/downloads)
- `yamllint` — YAML linter (`pip install yamllint` or `brew install yamllint`)
- `kustomize` v5.7.1 — required by `build-manifests.sh`/`verify-manifests.sh`; if not installed, `install.sh` creates a shim at `~/.local/bin/kustomize` backed by `kubectl`'s built-in kustomize
- `kubectl` — needed if `kustomize` is not installed (provides built-in kustomize v5.7.1)
- Optional: `KONFLUX_RELEASE_DATA_REPO_URL` (default: `https://gitlab.cee.redhat.com/releng/konflux-release-data.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- Optional: `OC_TOKEN` — cluster login token if no matching kubeconfig context is found

**Network:** Both `gitlab.cee.redhat.com` and the Konflux OpenShift cluster require
**VPN to be active**.

**Jira attachment:** The Jira issue must have `component_onboarding_details.yaml` attached. This
YAML is the source of truth for all component parameters (repo URL, branch, Dockerfile path,
context path, etc.).

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Idempotency: --existing-mr-url fast-path

If the skill is invoked with `--existing-mr-url <url>`, print:
```
MR already raised: <url>
```
and exit 0 immediately. The orchestrator passes this argument when the MR URL is already
recorded in `pipeline_state.json`, meaning this step was completed in a prior run.

---

## Step 0: Parse Inputs

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/parse_jira_url.sh" "${1:-}")"
[[ -z "$JIRA_URL" ]] && {
  echo "ERROR: Jira URL is required."
  echo "  Usage: /onboard-component-to-konflux-release-data <jira-url>"
  exit 1
}
echo "JIRA_URL : $JIRA_URL"
echo "JIRA_ID  : $JIRA_ID"
```

2. Resolve `KRD_URL` — execute this exact block; do NOT skip the `echo`:

   ```bash
   KRD_URL="${KONFLUX_RELEASE_DATA_REPO_URL:-https://gitlab.cee.redhat.com/releng/konflux-release-data.git}"
   echo "KONFLUX_RELEASE_DATA_REPO_URL=${KONFLUX_RELEASE_DATA_REPO_URL:-(not set, using default)}"
   echo "KRD_URL resolved to: $KRD_URL"
   ```

   **Never override or re-derive `KRD_URL` in later steps.**

> **IMPORTANT — `KRD_URL` is the single source of truth for all Git operations.**
> Use `$KRD_URL` for every Git operation in this skill: sparse clone (`--src-url`), push
> remote (`origin`), MR source URL (`--src-url`), and MR destination URL (`--dest-url`).
> **Never substitute a hardcoded URL or the upstream URL in place of `$KRD_URL`**, even if
> `$KRD_URL` appears to point to a personal fork. The user configured it intentionally.

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "GITLAB_USER GITLAB_TOKEN JIRA_USER_EMAIL JIRA_API_TOKEN" \
  --tools "uv oc yamllint kustomize"

# Resolve kustomize binary (standalone or ~/.local/bin shim)
KUSTOMIZE_BIN="kustomize"
if ! command -v kustomize &>/dev/null && [[ -x "${HOME}/.local/bin/kustomize" ]]; then
  KUSTOMIZE_BIN="${HOME}/.local/bin/kustomize"
  export PATH="${HOME}/.local/bin:${PATH}"
fi
```

---

## Step 2: Set Up Working Directory

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/init_workdir.sh" --jira-url "$JIRA_URL")"
echo "Working directory: $WORKDIR"
```

---

## Step 3: Fetch Jira Details and Component YAML

This step ensures both `component_onboarding_details.json` (full Jira issue) and
`component_onboarding_details.yaml` (component parameters) exist in `$WORKDIR`.

**3a. Fetch Jira issue details** (skip if `$WORKDIR/component_onboarding_details.json` already exists):

```bash
if [[ ! -f "$WORKDIR/component_onboarding_details.json" ]]; then
  cd "$WORKDIR"
  uv run --script <COMMON_SCRIPTS_DIR>/fetch_jira_details.py <jira-url>
fi
```

On exit 1: display stderr and stop with:
```
ERROR in Step 3a (Fetch Jira details): Could not fetch Jira issue. See details above. Aborting.
```

On success: `$WORKDIR/component_onboarding_details.json` is written.

**3b. Download component YAML** (skip if `$WORKDIR/component_onboarding_details.yaml` already exists):

```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/download_jira_attachment.py \
  <jira-url> component_onboarding_details.yaml
```

On exit 1: display stderr and stop with:
```
ERROR in Step 3b (Download YAML): Could not download 'component_onboarding_details.yaml' from Jira.
  Ensure the attachment exists on the Jira issue before running this skill.
```

**3c. Parse the YAML** by extracting values with `grep` and `awk`:

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/parse_component_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$COMMON_SCRIPTS_DIR")"
# Sets: COMPONENT_NAME, REPO_URL, REPO_BRANCH, PRODUCT_CONTEXT, QUAY_ORG, QUAY_VISIBILITY, QUAY_REPO_URI, IS_OPERATOR

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
CONTEXT_PATH=$(grep -m1     'context_path:'        "$YAML_FILE" | awk '{print $2}')
DOCKERFILE_PATH=$(grep -m1  'dockerfile_path:'     "$YAML_FILE" | awk '{print $2}')
TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null || echo "")
```

Extract and store these values (all are under the `inputs:` key):

| Variable | YAML field | Example |
|----------|-----------|---------|
| `COMPONENT_NAME` | `inputs.component_name` | `odh-ai-first-demo` |
| `REPO_URL` | `inputs.repo_url` | `https://github.com/rhoai-rhtap/odh-ai-first-demo` |
| `REPO_BRANCH` | `inputs.repo_branch` | `main` |
| `CONTEXT_PATH` | `inputs.context_path` | `maas-controller` |
| `DOCKERFILE_PATH` | `inputs.dockerfile_path` | `Dockerfile` |
| `TARGET_RHOAI_VERSION` | `inputs.target_rhoai_version` | `3.4` or `3.4-ea-2` |

`TARGET_RHOAI_VERSION` is optional — ODH tickets may not include it. Set to empty string if
absent; it is only validated when `PRODUCT_CONTEXT` is `RHOAI` (in Step 8).

Compute `KONFLUX_COMPONENT_NAME` (ODH default; will be overridden for RHOAI in Step 4):
- If `COMPONENT_NAME` already ends with `-ci`: `KONFLUX_COMPONENT_NAME="$COMPONENT_NAME"`
- Otherwise: `KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-ci"`

If any required field is missing, stop with:
```
ERROR in Step 3c: Missing required field '<field>' in component_onboarding_details.yaml. Aborting.
```

---

## Step 4: Determine Product Context

Set `PRODUCT_CONTEXT` to `ODH` or `RHOAI` using the following rules in order:

1. **From Jira key prefix**: if `<jira-id>` starts with `RHOAIENG` → `RHOAI`; if it starts
   with `RHODS` → `ODH`.
2. **From Jira title** (in `component_onboarding_details.json` at `fields.summary`): if the title
   contains "RHOAI" (case-insensitive) → `RHOAI`; if it contains "ODH" → `ODH`.
3. **Fallback**: Ask the user:
   > I could not determine the product context (ODH or RHOAI) from the Jira key or title.
   > Is this onboarding for ODH or RHOAI?

Based on `PRODUCT_CONTEXT`, set these variables:

| Variable | ODH | RHOAI |
|----------|-----|-------|
| `CLUSTER_INSTANCE` | `external` | `internal` |
| `KONFLUX_NAMESPACE` | `open-data-hub-tenant` | `rhoai-tenant` |
| `SPARSE_PATHS` | `tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant tenants-config/auto-generated/cluster/stone-prd-rh01/tenants/open-data-hub-tenant` | `tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant tenants-config/auto-generated/cluster/stone-prod-p02/tenants/rhoai-tenant` |
| `TARGET_YAML` | `tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant/opendatahub-ci-components.yaml` | _(set in Step 8-RHOAI-0 after parsing `target_rhoai_version`)_ |
| `KRD_APPLICATION` | `opendatahub-builds` | _(set in Step 8-RHOAI-0 after parsing `target_rhoai_version`)_ |
| `QUAY_ORG` | `opendatahub` | `rhoai` |

After setting `PRODUCT_CONTEXT`, recompute `KONFLUX_COMPONENT_NAME` for RHOAI. Skip this block if `PRODUCT_CONTEXT == "ODH"` (the `-ci` default from Step 3c is already correct).

If `PRODUCT_CONTEXT == "RHOAI"`:

```bash
if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
  KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-v${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-ea-${BASH_REMATCH[3]}"
elif [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
  KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-v${BASH_REMATCH[1]}-${BASH_REMATCH[2]}"
else
  echo "ERROR in Step 4 (RHOAI): Cannot parse target_rhoai_version '${TARGET_RHOAI_VERSION}'."
  echo "  Expected x.y or x.y-ea-n (e.g. 3.4 or 3.4-ea-2)."
  echo "  Re-generate the YAML with /create-component-onboarding-jira <jira-url>."
  exit 1
fi
echo "KONFLUX_COMPONENT_NAME : $KONFLUX_COMPONENT_NAME"
```

---

## Step 5: Check If Konflux Component Already Exists

```bash
bash <COMMON_SCRIPTS_DIR>/check_konflux_component.sh \
  "$KONFLUX_COMPONENT_NAME" "$KONFLUX_NAMESPACE" "$CLUSTER_INSTANCE"
```

- **Exit 0** (component exists): Update Jira and stop:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --add-label "konflux-component-created" \
    --comment "Konflux Component '$KONFLUX_COMPONENT_NAME' already exists in namespace '$KONFLUX_NAMESPACE'. No action needed."
  ```
  Print: `Konflux Component already exists. Nothing to do.` and **stop**.

- **Exit 1** (does not exist): Continue to Step 7.

- **Exit 2** (tool/login error): Display the error output and stop with:
  ```
  ERROR in Step 5: Could not check Konflux component status. Check VPN and OC_TOKEN.
  ```

---

## Step 7: Set Up Playpen (Sparse Clone)

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

# For RHOAI, also check out the ReleasePlanAdmission config directory
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  SPARSE_PATHS="$SPARSE_PATHS config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai"
fi

PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash <COMMON_SCRIPTS_DIR>/setup_gitlab_playpen.sh \
  --src-url "$KRD_URL" \
  --src-branch main \
  --dest-branch "<jira-id>" \
  --sparse-files "$SPARSE_PATHS")
```

Parse `PLAYPEN_OUTPUT`:
- Line 1 → `CLONE_DIR` (absolute path to the clone directory — derived from the repo name,
  e.g. `konflux-release-data-playpen` inside `$WORKDIR`)
- Line 2 → `DEST_BRANCH` (the branch created and pushed)

On exit 1: display stderr and stop with:
```
ERROR in Step 7 (Playpen setup): Clone or push failed. See details above.
  Check VPN connectivity and GITLAB_TOKEN write_repository scope.
```

If the initial push fails with "shallow update not allowed", unshallow and retry:
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "<jira-id>"
```

---

## Step 8: Modify the Target YAML File

**Idempotency check and YAML append:**

```bash
if grep -q "name: $KONFLUX_COMPONENT_NAME" "$CLONE_DIR/$TARGET_YAML" 2>/dev/null; then
  echo "Component entry '$KONFLUX_COMPONENT_NAME' already present in $TARGET_YAML — skipping append."
else
  COMPONENT_YAML=$(cat <<EOF
apiVersion: appstudio.redhat.com/v1alpha1
kind: Component
metadata:
  annotations:
    build.appstudio.openshift.io/request: configure-pac-no-mr
    mintmaker.appstudio.redhat.com/disabled: "true"
    build.appstudio.openshift.io/pipeline: '{"name":"docker-build-multi-platform-oci-ta","bundle":"latest"}'
  name: ${KONFLUX_COMPONENT_NAME}
spec:
  application: ${KRD_APPLICATION}
  componentName: ${KONFLUX_COMPONENT_NAME}
  containerImage: quay.io/${QUAY_ORG}/${COMPONENT_NAME}
  source:
    git:
      context: ${CONTEXT_PATH}
      dockerfileUrl: ${DOCKERFILE_PATH}
      revision: ${REPO_BRANCH}
      url: ${REPO_URL}
EOF
)
  uv run --script "$COMMON_SCRIPTS_DIR/edit_yaml.py" append-yaml-doc \
    "$CLONE_DIR/$TARGET_YAML" \
    --yaml-string "$COMPONENT_YAML"
fi
```

On exit 1 from `edit_yaml.py`: display stderr and stop with:
```
ERROR in Step 8 (Modify YAML): Could not append Component document to $TARGET_YAML. See details above. Aborting.
```

Verify the entry was written:
```bash
grep -q "name: $KONFLUX_COMPONENT_NAME" "$CLONE_DIR/$TARGET_YAML" \
  || { echo "ERROR: $KONFLUX_COMPONENT_NAME not found in $TARGET_YAML after append."; exit 1; }
```

---

**Step 8 RHOAI: Modify RHOAI-Specific Files** (skip entirely if `PRODUCT_CONTEXT != "RHOAI"`)

**8-RHOAI-0. Validate and parse `TARGET_RHOAI_VERSION`**

```bash
if [[ -z "$TARGET_RHOAI_VERSION" ]]; then
  echo "ERROR in Step 8 (RHOAI): target_rhoai_version is missing from component_onboarding_details.yaml."
  echo "  Re-generate the YAML with /create-component-onboarding-jira <jira-url>."
  exit 1
fi

if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
  VERSION_X="${BASH_REMATCH[1]}"
  VERSION_Y="${BASH_REMATCH[2]}"
  VERSION_N="${BASH_REMATCH[3]}"
  VERSION_NAME="v${VERSION_X}.${VERSION_Y}-ea.${VERSION_N}"
  RPA_VAR="v${VERSION_X}-${VERSION_Y}-ea-${VERSION_N}"
elif [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
  VERSION_X="${BASH_REMATCH[1]}"
  VERSION_Y="${BASH_REMATCH[2]}"
  VERSION_N=""
  VERSION_NAME="v${VERSION_X}.${VERSION_Y}"
  RPA_VAR="v${VERSION_X}-${VERSION_Y}"
else
  echo "ERROR in Step 8 (RHOAI): Cannot parse target_rhoai_version '${TARGET_RHOAI_VERSION}'."
  echo "  Expected canonical form: x.y  OR  x.y-ea-n  (e.g. 3.4 or 3.4-ea-2)"
  exit 1
fi
echo "VERSION_NAME : $VERSION_NAME"
echo "RPA_VAR      : $RPA_VAR"

# Set TARGET_YAML for RHOAI — points to the ProjectDevelopmentStream file for this version
TARGET_YAML="tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/${VERSION_NAME}/ProjectDevelopmentStream-${VERSION_NAME}.yaml"

# Set KRD_APPLICATION for RHOAI based on whether this is an EA release
if [[ -n "$VERSION_N" ]]; then
  KRD_APPLICATION="rhoai-v${VERSION_X}-${VERSION_Y}-ea-${VERSION_N}"
else
  KRD_APPLICATION="rhoai-v${VERSION_X}-${VERSION_Y}"
fi

echo "TARGET_YAML     : $TARGET_YAML"
echo "KRD_APPLICATION : $KRD_APPLICATION"
```

Also derive the context path used in the template:
```bash
if [[ "$CONTEXT_PATH" == "./" || "$CONTEXT_PATH" == "." ]]; then
  CONTEXT_PATH_NORMALIZED="."
else
  CONTEXT_PATH_NORMALIZED="$CONTEXT_PATH"
fi
```

---

**8-RHOAI-1. Modify `ProjectDevelopmentStream-<VERSION_NAME>.yaml`**

File path:
```
$CLONE_DIR/tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/${VERSION_NAME}/ProjectDevelopmentStream-${VERSION_NAME}.yaml
```

- **If file not found:** update Jira with an appropriate comment, then stop:
  ```
  ERROR in Step 8 (RHOAI): ProjectDevelopmentStream-${VERSION_NAME}.yaml not found.
    Sprint onboarding for version '${VERSION_NAME}' is pending.
    Complete sprint onboarding first and update the Jira accordingly.
  ```

- **Idempotency check:** use `Read` to read the file. If a line containing
  `name: ${COMPONENT_NAME}-{{.versionName}}` is already present, skip to 8-RHOAI-2.

- **Append** to the `spec.resources` array using `Edit`. Substitute `COMPONENT_NAME`,
  `CONTEXT_PATH_NORMALIZED`, `DOCKERFILE_PATH`, and `REPO_URL` with their variable values.
  Write `{{.versionName}}` and `{{.branch}}` **verbatim** — they are Go template placeholders
  and must NOT be replaced with actual values.

  ```yaml
  - apiVersion: appstudio.redhat.com/v1alpha1
    kind: Component
    metadata:
      annotations:
        build.appstudio.openshift.io/pipeline: '{"name":"docker-build-multi-platform-oci-ta","bundle":"latest"}'
        build.appstudio.openshift.io/request: configure-pac-no-mr
      name: <COMPONENT_NAME>-{{.versionName}}
    spec:
      application: rhoai-{{.versionName}}
      build-nudges-ref:
        - odh-operator-{{.versionName}}
      componentName: <COMPONENT_NAME>-{{.versionName}}
      containerImage: quay.io/rhoai/<COMPONENT_NAME>-rhel9
      source:
        git:
          context: <CONTEXT_PATH_NORMALIZED>
          dockerfileUrl: <DOCKERFILE_PATH>
          revision: "{{.branch}}"
          url: <REPO_URL>
  ```

  Match the indentation used by existing entries in the file. After editing, use `Read` to verify
  the entry is present and surrounding entries are undisturbed.

---

**8-RHOAI-2. Modify `rhoai-onprem-<RPA_VAR>-components-stage.yaml`**

File path:
```
$CLONE_DIR/config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-${RPA_VAR}-components-stage.yaml
```

- **If file not found:** update Jira with an appropriate comment, then stop:
  ```
  ERROR in Step 8 (RHOAI): rhoai-onprem-${RPA_VAR}-components-stage.yaml not found.
    Sprint onboarding for version '${VERSION_NAME}' is pending.
    Complete sprint onboarding first and update the Jira accordingly.
  ```

- **Idempotency check:** use `Read` to read the file. If `name: ${COMPONENT_NAME}-${RPA_VAR}`
  is already present in `spec.data.mapping.components`, skip to 8-RHOAI-3.

- **Append** to `spec.data.mapping.components` using `Edit`:
  ```yaml
  - name: <COMPONENT_NAME>-<RPA_VAR>
    repositories:
      - url: registry.stage.redhat.io/rhoai/<COMPONENT_NAME>-rhel9
  ```

  After editing, use `Read` to verify the entry is present.

---

**8-RHOAI-3. Modify `rhoai-onprem-<RPA_VAR>-components-prod.yaml`**

File path:
```
$CLONE_DIR/config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-${RPA_VAR}-components-prod.yaml
```

- **If file not found:** update Jira with an appropriate comment, then stop:
  ```
  ERROR in Step 8 (RHOAI): rhoai-onprem-${RPA_VAR}-components-prod.yaml not found.
    Sprint onboarding for version '${VERSION_NAME}' is pending.
    Complete sprint onboarding first and update the Jira accordingly.
  ```

- **Idempotency check and append:**

  ```bash
  RPA_FILE="$CLONE_DIR/config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-${RPA_VAR}-components-prod.yaml"

  if grep -q "name: ${COMPONENT_NAME}-${RPA_VAR}" "$RPA_FILE" 2>/dev/null; then
    echo "Entry '${COMPONENT_NAME}-${RPA_VAR}' already present in $RPA_FILE — skipping."
  else
    uv run --script "$COMMON_SCRIPTS_DIR/edit_yaml.py" append-rpa-component \
      "$RPA_FILE" \
      --array-key "spec.data.mapping.components" \
      --name "${COMPONENT_NAME}-${RPA_VAR}" \
      --url "registry.redhat.io/rhoai/${COMPONENT_NAME}-rhel9"
  fi
  ```

  Note: stage uses `registry.stage.redhat.io`; prod uses `registry.redhat.io` (no `stage.`).

---

**8-RHOAI-4. Add to `automation/resources.yaml`** (RHOAI only)

File path:
```
$CLONE_DIR/tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/automation/resources.yaml
```

- **If file not found:** update Jira with an appropriate comment, then stop:
  ```
  ERROR in Step 8 (RHOAI): automation/resources.yaml not found.
    Sprint onboarding for rhoai-tenant/automation may be incomplete.
    Verify the file exists in the repository and re-run.
  ```

- **Idempotency check:** If a line containing `name: pull-request-pipelines-${COMPONENT_NAME}` is already present in the file, skip to step 8d.

- **Append** the following YAML document to the file using `edit_yaml.py`:

  ```bash
  AUTOMATION_FILE="$CLONE_DIR/tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/automation/resources.yaml"

  AUTOMATION_YAML=$(cat <<EOF
  ---
  apiVersion: appstudio.redhat.com/v1alpha1
  kind: Component
  metadata:
    annotations:
      build.appstudio.openshift.io/request: configure-pac-no-mr
      build.appstudio.openshift.io/pipeline: '{"name":"docker-build-multi-platform-oci-ta","bundle":"latest"}'
    name: pull-request-pipelines-${COMPONENT_NAME}
  spec:
    application: automation
    componentName: pull-request-pipelines-${COMPONENT_NAME}
    containerImage: quay.io/rhoai/pull-request-pipelines
    source:
      git:
        context: ${CONTEXT_PATH_NORMALIZED}
        dockerfileUrl: ${DOCKERFILE_PATH}
        url: ${REPO_URL}
  EOF
  )

  uv run --script "$COMMON_SCRIPTS_DIR/edit_yaml.py" append-yaml-doc \
    "$AUTOMATION_FILE" \
    --yaml-string "$AUTOMATION_YAML"
  ```

  On exit 1 from `edit_yaml.py`: display stderr and stop with:
  ```
  ERROR in Step 8-RHOAI-4 (Modify automation/resources.yaml): Could not append Component document. See details above. Aborting.
  ```

  After appending, verify the entry is present:
  ```bash
  grep -q "name: pull-request-pipelines-${COMPONENT_NAME}" "$AUTOMATION_FILE" \
    || { echo "ERROR: pull-request-pipelines-${COMPONENT_NAME} not found in automation/resources.yaml after append."; exit 1; }
  ```

---

**8d. Run `build-manifests.sh`** to regenerate the `auto-generated/` directory.
Pass `$KUSTOMIZE_BIN` (resolved in Step 1) so the script uses the correct binary or shim:

```bash
cd "$CLONE_DIR/tenants-config"
./build-manifests.sh "$KUSTOMIZE_BIN"
```

On non-zero exit: display the output and stop with:
```
ERROR in Step 8d (build-manifests): Manifest generation failed. See output above. Fix the issue before proceeding.
```

**8e. Run `yamllint`** from the playpen root to catch any YAML issues introduced:

```bash
cd "$CLONE_DIR"
yamllint -s -f colored .gitlab-ci.yml .gitlab tenants-config/cluster
```

If `yamllint` reports errors:
- Read the error output — it lists the file path and line number for each violation.
- Run `cat <offending-file>` to inspect the error location and use `sed -i'' ...` or a
  targeted bash one-liner to fix the indentation, trailing spaces, or line-length issue.
- Re-run `yamllint` after each fix until it exits 0 before continuing.

**8f. Stage and commit all changes** (source YAML + auto-generated manifests):

```bash
cd "$CLONE_DIR"
git add -A
git commit -m "Add $KONFLUX_COMPONENT_NAME Component to konflux-release-data"
```

**8g. Run `verify-manifests.sh`** to validate the generated manifests:

```bash
cd "$CLONE_DIR/tenants-config"
./verify-manifests.sh "$KUSTOMIZE_BIN"
```

If `verify-manifests.sh` exits non-zero:
- Read its error output to identify which manifest file is invalid.
- Run `cat <reported-file>` to inspect the issue and use `sed -i'' ...` or a bash one-liner to fix it.
- Re-run `./verify-manifests.sh` after each fix until it exits 0.
- If you had to make additional file edits, re-stage and amend the commit:
  ```bash
  cd "$CLONE_DIR"
  git add -A
  git commit --amend --no-edit
  ```

**8h. Push the branch to the remote:**

```bash
cd "$CLONE_DIR"
git push origin "$DEST_BRANCH"
```

If push fails with "shallow update not allowed":
```bash
git fetch --unshallow origin
git push origin "$DEST_BRANCH"
```

---

## Step 9: Raise MR (up to 3 attempts)

Step 8 already committed and pushed all changes. Proceed directly to raising the MR.

**Raise MR** — attempt up to 3 times:

```bash
MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script <COMMON_SCRIPTS_DIR>/raise_gitlab_mr.py \
  --src-url "$KRD_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$KRD_URL" \
  --dest-branch main \
  --title "Add $KONFLUX_COMPONENT_NAME Component for $COMPONENT_NAME" \
  --description "Add Konflux Component '$KONFLUX_COMPONENT_NAME' to $TARGET_YAML.

Product: $PRODUCT_CONTEXT
Application: $KRD_APPLICATION
Container image: quay.io/$QUAY_ORG/$COMPONENT_NAME
Source repo: $REPO_URL @ $REPO_BRANCH
Jira: <jira-url>")
```

On success: `MR_URL` is set.

On failure:
- "Branch not found" → re-run the push and retry
- "Connection error / VPN" → tell user to check VPN and retry
- Any other error → retry (up to 3 times total)

After 3 failures, stop with:
```
ERROR in Step 9 (Raise MR): Could not create MR after 3 attempts. See errors above. Aborting.
```

After a successful MR creation, update Jira:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --add-label "krd-mr-raised" \
  --comment "GitLab MR raised to create Konflux Component '$KONFLUX_COMPONENT_NAME'.

MR URL: $MR_URL

The Component will be provisioned on the Konflux cluster once this MR is merged."
```

Print the MR URL and stop:
```
MR raised: $MR_URL
```

The skill is complete. The orchestrator will monitor the MR separately.

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITLAB_USER` not set | Step 1 | `export GITLAB_USER=yourusername` |
| `GITLAB_TOKEN` not set | Step 1 | `export GITLAB_TOKEN=yourtoken` |
| `JIRA_USER_EMAIL` not set | Step 1 | `export JIRA_USER_EMAIL=you@redhat.com` |
| `JIRA_API_TOKEN` not set | Step 1 | `export JIRA_API_TOKEN=your-token` |
| `uv` not installed | Step 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `oc` not installed | Step 1 | Download from console.redhat.com/openshift/downloads |
| `component_onboarding_details.yaml` not attached to Jira | Step 3b | Upload the YAML to the Jira issue |
| VPN not active | Steps 5, 7, 9 | Activate VPN and re-run |
| `OC_TOKEN` not set | Step 5 | `export OC_TOKEN=<token-from-openshift-console>` |
| Shallow push rejected | Steps 7, 9 | `git fetch --unshallow origin` then retry push |
| Clone fails | Step 7 | Check VPN and GITLAB_TOKEN `write_repository` scope |
| MR creation fails 3× | Step 9 | Check VPN; inspect stderr; fix manually |
| `target_rhoai_version` empty | Step 8 (RHOAI) | Re-generate YAML with `/create-component-onboarding-jira` |
| `target_rhoai_version` format invalid | Step 8 (RHOAI) | Expected `x.y` or `x.y-ea-n` (e.g. `3.4` or `3.4-ea-2`) |
| `ProjectDevelopmentStream-*.yaml` not found | Step 8 (RHOAI) | Sprint onboarding pending — complete it first |
| `rhoai-onprem-*-components-stage.yaml` not found | Step 8 (RHOAI) | Sprint onboarding pending — complete it first |
| `rhoai-onprem-*-components-prod.yaml` not found | Step 8 (RHOAI) | Sprint onboarding pending — complete it first |
