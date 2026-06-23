#!/usr/bin/env bash
# resolve_union_conflicts.sh — Auto-resolve merge conflicts using git's union merge driver.
#
# Called by git_commit_push.sh when a push is rejected due to a non-fast-forward
# (another onboarding job merged first). Configures .git/info/attributes for known
# shared YAML files, merges the target branch, validates the result, and reports
# to Jira.
#
# Exit codes:
#   0  Conflicts auto-resolved and YAML valid — caller may retry push normally
#   1  Merge failed or YAML invalid — manual intervention required
#
# Usage:
#   bash resolve_union_conflicts.sh \
#     --clone-dir  <path> \
#     --target-branch <branch> \
#     [--jira-url <url>]
set -euo pipefail

CLONE_DIR=""
TARGET_BRANCH=""
JIRA_URL=""

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clone-dir)     CLONE_DIR="$2";     shift 2 ;;
    --target-branch) TARGET_BRANCH="$2"; shift 2 ;;
    --jira-url)      JIRA_URL="$2";      shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$CLONE_DIR" ]]     && { echo "ERROR: --clone-dir is required" >&2; exit 1; }
[[ -z "$TARGET_BRANCH" ]] && { echo "ERROR: --target-branch is required" >&2; exit 1; }

cd "$CLONE_DIR"

REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
REPO_NAME=$(basename "$REMOTE_URL" .git)

# Inject GitLab credentials into remote URL so push works without interactive prompt
# Only inject if credentials are not already present in the URL
if [[ "$REMOTE_URL" == *"gitlab.cee.redhat.com"* && "$REMOTE_URL" != *"@"* && -n "${GITLAB_TOKEN:-}" ]]; then
  AUTH_REMOTE_URL="${REMOTE_URL/https:\/\//https://oauth2:${GITLAB_TOKEN}@}"
  git remote set-url origin "$AUTH_REMOTE_URL" 2>/dev/null || true
fi
ATTRS_FILE=".git/info/attributes"
mkdir -p "$(dirname "$ATTRS_FILE")"

# ── Set union merge attributes per repo ───────────────────────────────────────
# The union merge driver keeps ALL lines from both sides on conflicts — safe for
# append-only YAML lists. Configured locally (.git/info/attributes) — never
# committed or pushed to the remote.

case "$REMOTE_URL" in
  *konflux-release-data*)
    cat >> "$ATTRS_FILE" <<'EOF'
tenants-config/**/*.yaml merge=union
config/**/*.yaml merge=union
EOF
    ;;
  *pyxis-repo-configs*)
    cat >> "$ATTRS_FILE" <<'EOF'
products/rhoai/rhoai.yaml merge=union
products/rhoai-beta/rhoai.yaml merge=union
EOF
    ;;
  *RHOAI-Build-Config*)
    cat >> "$ATTRS_FILE" <<'EOF'
bundle/bundle-patch.yaml merge=union
config/build-config.yaml merge=union
EOF
    ;;
  *ODH-Build-Config*)
    echo "bundle/bundle-patch.yaml merge=union" >> "$ATTRS_FILE"
    ;;
  *rhods-devops-infra*)
    cat >> "$ATTRS_FILE" <<'EOF'
upstream-source-map.yaml merge=union
main-release-source-map.yaml merge=union
EOF
    ;;
  *konflux-central*)
    cat >> "$ATTRS_FILE" <<'EOF'
config.yaml merge=union
**/*.yml merge=union
EOF
    ;;
  *odh-konflux-central*)
    cat >> "$ATTRS_FILE" <<'EOF'
config.yaml merge=union
.github/workflows/odh-konflux-onboarder.yml merge=union
EOF
    ;;
esac

# Ensure git identity is set (CI runners often have no global config)
git config --get user.email &>/dev/null || git config user.email "rhoai-onboarding-bot@redhat.com"
git config --get user.name  &>/dev/null || git config user.name  "RHOAI Onboarding Bot"

echo "[union-resolve] Configured union merge attributes for $REPO_NAME"

# ── Fetch target branch (explicit refspec works for shallow clones) ───────────
echo "[union-resolve] Fetching origin/$TARGET_BRANCH..."
git fetch origin "${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}" 2>/dev/null || \
  git fetch origin "$TARGET_BRANCH" 2>/dev/null || true

# ── Merge with union driver ────────────────────────────────────────────────────
echo "[union-resolve] Merging origin/$TARGET_BRANCH with union driver..."
_do_merge() {
  git merge "origin/$TARGET_BRANCH" -m "Auto-resolve conflicts via union merge [onboarding-bot]" 2>&1
}

MERGE_OUT=$(_do_merge) || {
  echo "$MERGE_OUT"
  if echo "$MERGE_OUT" | grep -q "unrelated histories"; then
    echo "[union-resolve] Shallow clone — unshallowing to find common ancestor..." >&2
    git fetch --unshallow 2>/dev/null || true
    MERGE_OUT=$(_do_merge) || {
      echo "$MERGE_OUT"
      echo "[union-resolve] ERROR: Union merge failed — manual resolution required." >&2
      if [[ -n "$JIRA_URL" ]]; then
        uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
          --comment "[union-resolve] FAILED — Merge conflict in \`${REPO_NAME}\` (branch: \`${TARGET_BRANCH}\`) could not be auto-resolved. Manual intervention required." || true
      fi
      exit 1
    }
  elif echo "$MERGE_OUT" | grep -q "CONFLICT\|conflict"; then
    echo "[union-resolve] ERROR: Union merge has unresolved conflicts — manual resolution required." >&2
    git merge --abort 2>/dev/null || true
    if [[ -n "$JIRA_URL" ]]; then
      uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --comment "[union-resolve] FAILED — Could not auto-resolve conflicts in \`${REPO_NAME}\`. Manual intervention required." || true
    fi
    exit 1
  else
    echo "[union-resolve] ERROR: Union merge failed — manual resolution required." >&2
    exit 1
  fi
}

# ── Validate YAML files changed relative to the new target ───────────────────
CHANGED_YAML=$(git diff --name-only "origin/$TARGET_BRANCH" 2>/dev/null | grep -E '\.ya?ml$' || true)
INVALID=()
for f in $CHANGED_YAML; do
  [[ -f "$f" ]] || continue
  if ! python3 -c "
import yaml, re, sys
text = open('$f').read()
docs = list(yaml.safe_load_all(text))
# Detect silent key overwrite: more top-level apiVersion markers than parsed docs
# means two YAML documents were accidentally merged without a --- separator
api_markers = len(re.findall(r'(?m)^apiVersion:', text))
if api_markers > len(docs):
    sys.exit(f'silent-merge: {api_markers} apiVersion markers but only {len(docs)} docs parsed')
" 2>/dev/null; then
    INVALID+=("$f")
  fi
done

if [[ ${#INVALID[@]} -gt 0 ]]; then
  echo "[union-resolve] ERROR: YAML validation failed after union merge: ${INVALID[*]}" >&2
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "[union-resolve] BLOCKED — YAML validation failed after auto-merge in \`${REPO_NAME}\`.

Invalid files: ${INVALID[*]}

The union merge produced structurally invalid YAML. Manual resolution is required.
Branch: \`$(git rev-parse --abbrev-ref HEAD)\` in ${REMOTE_URL}" || true
  fi
  exit 1
fi

echo "[union-resolve] Union merge succeeded. YAML validation passed."
if [[ -n "$JIRA_URL" ]]; then
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "[union-resolve] INFO — Merge conflict in \`${REPO_NAME}\` auto-resolved via union merge strategy.

Both sets of changes have been incorporated. YAML validation passed.
Branch updated: \`$(git rev-parse --abbrev-ref HEAD)\`" || true
fi
exit 0
