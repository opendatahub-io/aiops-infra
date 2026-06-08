#!/usr/bin/env bash
# install.sh — Install the conforma-exception-create skill for Claude Code or Cursor.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-create-ai-skill/skills/conforma-exception-create/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-create-ai-skill/skills/conforma-exception-create/install.sh | bash -s -- --target cursor
#   curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-create-ai-skill/skills/conforma-exception-create/install.sh | bash -s -- --target claude
#   curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-create-ai-skill/skills/conforma-exception-create/install.sh | bash -s -- --project /path/to/project
#
# Options:
#   --target claude|cursor|both   Where to install (default: both)
#   --project PATH                Also install as project-local skill in PATH/.claude/skills/
#   --branch BRANCH               Git branch to install from (default: main)
#   --uninstall                   Remove previously installed skill
#   --dry-run                     Show what would be done without making changes

set -euo pipefail

REPO="opendatahub-io/aiops-infra"
REPO_URL="https://github.com/${REPO}.git"
SKILL_PATH="skills/conforma-exception-create"
SKILL_NAME="conforma-exception-create"
BRANCH="conforma-exception-create-ai-skill"

CLAUDE_SKILLS_DIR="${HOME}/.claude/skills"
CURSOR_SKILLS_DIR="${HOME}/.cursor/skills-cursor"

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}      $*"; }
info() { echo -e "${BLUE}[INFO]${NC}    $*"; }
warn() { echo -e "${YELLOW}[SKIP]${NC}    $*"; }
err()  { echo -e "${RED}[ERROR]${NC}   $*" >&2; }

TARGET="both"
PROJECT_PATH=""
DRY_RUN=false
UNINSTALL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      [[ -z "${2:-}" ]] && { err "--target requires: claude, cursor, or both"; exit 1; }
      TARGET="$2"; shift 2 ;;
    --project)
      [[ -z "${2:-}" ]] && { err "--project requires a path"; exit 1; }
      PROJECT_PATH="$2"; shift 2 ;;
    --branch)
      [[ -z "${2:-}" ]] && { err "--branch requires a branch name"; exit 1; }
      BRANCH="$2"; shift 2 ;;
    --uninstall)  UNINSTALL=true; shift ;;
    --dry-run)    DRY_RUN=true; shift ;;
    *) err "Unknown argument: $1"; exit 1 ;;
  esac
done

run() {
  if [[ "$DRY_RUN" == true ]]; then
    info "(dry-run) $*"
  else
    "$@"
  fi
}

_install_to_dir() {
  local dest_dir="$1"
  local dest="$dest_dir/$SKILL_NAME"
  local label="$2"

  if [[ "$UNINSTALL" == true ]]; then
    if [[ -d "$dest" ]]; then
      run rm -rf "$dest"
      ok "Removed $label skill from $dest"
    else
      warn "No $label skill found at $dest"
    fi
    return
  fi

  if [[ -d "$dest" ]]; then
    info "Updating existing installation at $dest..."
    if [[ -d "$dest/.git" ]]; then
      run git -C "$dest" fetch origin "$BRANCH" --depth=1
      run git -C "$dest" checkout "origin/$BRANCH" -- .
      ok "Updated $label skill (git pull)"
    else
      run rm -rf "$dest"
      _clone_skill "$dest"
      ok "Replaced $label skill (fresh clone)"
    fi
  else
    run mkdir -p "$dest_dir"
    _clone_skill "$dest"
    ok "Installed $label skill to $dest"
  fi
}

_clone_skill() {
  local dest="$1"
  local tmpdir
  tmpdir="$(mktemp -d)"

  git clone --depth=1 --branch="$BRANCH" --filter=blob:none --sparse \
    "$REPO_URL" "$tmpdir/repo" 2>/dev/null
  git -C "$tmpdir/repo" sparse-checkout set "$SKILL_PATH" 2>/dev/null

  mv "$tmpdir/repo/$SKILL_PATH" "$dest"
  rm -rf "$tmpdir"
}

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  conforma-exception-create skill installer"
echo "════════════════════════════════════════════════════════════"
echo "  Source: github.com/${REPO} (branch: ${BRANCH})"
echo "  Target: ${TARGET}"
if [[ -n "$PROJECT_PATH" ]]; then
  echo "  Project: ${PROJECT_PATH}"
fi
echo "  Dry run: ${DRY_RUN}"
echo "════════════════════════════════════════════════════════════"
echo ""

if [[ "$TARGET" == "claude" || "$TARGET" == "both" ]]; then
  _install_to_dir "$CLAUDE_SKILLS_DIR" "Claude Code"
fi

if [[ "$TARGET" == "cursor" || "$TARGET" == "both" ]]; then
  _install_to_dir "$CURSOR_SKILLS_DIR" "Cursor"
fi

if [[ -n "$PROJECT_PATH" ]]; then
  _install_to_dir "$PROJECT_PATH/.claude/skills" "project-local"
fi

echo ""
if [[ "$UNINSTALL" == true ]]; then
  echo -e "${GREEN}Uninstall complete.${NC}"
else
  echo -e "${GREEN}Installation complete.${NC}"
  echo ""
  echo "Next steps:"
  echo "  1. Ensure glab is installed:  sudo dnf install glab  (or: brew install glab)"
  echo "  2. Authenticate Jira:         echo \"\$TOKEN\" | acli jira auth login --site redhat.atlassian.net --email \"\$USER@redhat.com\" --token"
  echo "  3. Authenticate GitLab:       glab auth login --hostname gitlab.cee.redhat.com --token \"\$TOKEN\""
  echo ""
  echo "Usage:"
  echo "  Claude Code:  Ask \"create a conforma exception for RHOAIENG-XXXXX\""
  echo "  Cursor:       Ask \"create a conforma exception for RHOAIENG-XXXXX\""
fi
