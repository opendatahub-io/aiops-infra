#!/usr/bin/env bash
# install.sh — Install RHOAI/ODH component onboarding skills into ~/.claude/skills/
#
# DEPRECATED: Marketplace installation is the primary distribution method.
# This script is retained for local development within the aiops-infra repo only.
# Shared scripts now live at the repo root (scripts/) and are accessible via
# marketplace caching or when running skills from the repo root directly.
#
# Creates symlinks in ~/.claude/skills/ for each skill directory,
# making all skills available to Claude Code globally.
#
# Usage:
#   bash .claude/skills/install.sh [--force] [--uninstall] [--list] [--user USER]
#
# Options:
#   --force      Overwrite existing symlinks (update to latest)
#   --uninstall  Remove symlinks installed by this script
#   --list       Show what would be installed without making changes
#   --user USER  Install skills into USER's home (~USER/.claude/skills/)
#                instead of the current user's. Useful in CI where setup
#                runs as root but Claude runs as a different user.

set -euo pipefail

SKILLS_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DST="${HOME}/.claude/skills"

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[installed]${NC}  $1 → $2"; }
skip() { echo -e "${YELLOW}[exists]${NC}     $1 (use --force to update)"; }
gone() { echo -e "${GREEN}[removed]${NC}    $1"; }
info() { echo -e "             $*"; }
err()  { echo -e "${RED}[error]${NC}      $*" >&2; }

FORCE=false
UNINSTALL=false
LIST=false
TARGET_USER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)     FORCE=true;     shift ;;
    --uninstall) UNINSTALL=true; shift ;;
    --list)      LIST=true;      shift ;;
    --user)
      [[ -z "${2:-}" ]] && { err "--user requires a username"; exit 1; }
      TARGET_USER="$2"; shift 2 ;;
    *) err "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ -n "$TARGET_USER" ]]; then
  TARGET_HOME="$(eval echo "~$TARGET_USER" 2>/dev/null)"
  if [[ "$TARGET_HOME" == "~$TARGET_USER" || ! -d "$TARGET_HOME" ]]; then
    err "Cannot resolve home directory for user '$TARGET_USER'"
    exit 1
  fi
  SKILLS_DST="$TARGET_HOME/.claude/skills"
fi

# Collect everything to install: skill dirs + common/
TARGETS=()
for entry in "$SKILLS_SRC"/*/; do
  name="$(basename "$entry")"
  # Only include directories that contain a SKILL.md
  [[ -f "$entry/SKILL.md" ]] && TARGETS+=("$name")
done

# ── List mode ───────────────────────────────────────────────────────────────────
if [[ "$LIST" == true ]]; then
  echo "Skills to install from: $SKILLS_SRC"
  echo "Install target:         $SKILLS_DST"
  echo ""
  for name in "${TARGETS[@]}"; do
    dst="$SKILLS_DST/$name"
    if [[ -L "$dst" ]]; then
      echo "  [symlinked] $name → $(readlink "$dst")"
    elif [[ -e "$dst" ]]; then
      echo "  [exists]    $name (not a symlink — use --force to replace)"
    else
      echo "  [pending]   $name"
    fi
  done
  exit 0
fi

mkdir -p "$SKILLS_DST"
if [[ -n "$TARGET_USER" ]]; then
  chown -R "$TARGET_USER" "$(dirname "$SKILLS_DST")"
fi

# ── Uninstall mode ──────────────────────────────────────────────────────────────
if [[ "$UNINSTALL" == true ]]; then
  echo "Uninstalling skills from $SKILLS_DST ..."
  for name in "${TARGETS[@]}"; do
    dst="$SKILLS_DST/$name"
    if [[ -L "$dst" && "$(readlink "$dst")" == "$SKILLS_SRC/$name" ]]; then
      rm "$dst"
      gone "$name"
    elif [[ -e "$dst" ]]; then
      info "$name exists but was not installed by this script — skipping"
    fi
  done
  echo ""
  echo "Done. Remaining skills in $SKILLS_DST:"
  ls "$SKILLS_DST" 2>/dev/null || echo "  (empty)"
  exit 0
fi

# ── Install mode ─────────────────────────────────────────────────────────────────
echo "Installing skills from: $SKILLS_SRC"
echo "Into:                   $SKILLS_DST"
echo ""

for name in "${TARGETS[@]}"; do
  src="$SKILLS_SRC/$name"
  dst="$SKILLS_DST/$name"

  if [[ -L "$dst" ]]; then
    if [[ "$FORCE" == true ]]; then
      rm "$dst"
      ln -s "$src" "$dst"
      ok "$name" "$dst"
    else
      skip "$name"
    fi
  elif [[ -e "$dst" ]]; then
    err "$name already exists at $dst but is not a symlink."
    info "Remove it manually or use --force to replace it."
  else
    ln -s "$src" "$dst"
    ok "$name" "$dst"
  fi
done

if [[ -n "$TARGET_USER" ]]; then
  chown -R "$TARGET_USER" "$(dirname "$SKILLS_DST")"
fi

echo ""
echo "Done. Installed skills:"
for name in "${TARGETS[@]}"; do
  [[ -L "$SKILLS_DST/$name" ]] && echo "  • $name"
done
