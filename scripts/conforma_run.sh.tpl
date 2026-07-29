#!/usr/bin/env bash
# conforma_run.sh — resolve aiops-infra repo root and dispatch to a Python script.
# Installed to ~/.conforma/bin/conforma_run.sh by init_conforma_run.py.
set -euo pipefail

_resolve_root() {
    local ctx="$HOME/.conforma/.conforma-active/context.yaml"
    if [ -f "$ctx" ]; then
        local root
        root="$(grep '^aiops_infra_root:' "$ctx" | cut -d' ' -f2-)"
        root="${root/#\~/$HOME}"
        if [ -n "$root" ] && [ -f "$root/pyproject.toml" ]; then
            echo "$root"; return 0
        fi
    fi
    if [ -n "${AIOPS_INFRA_ROOT:-}" ] && [ -f "$AIOPS_INFRA_ROOT/pyproject.toml" ]; then
        echo "$AIOPS_INFRA_ROOT"; return 0
    fi
    local git_root
    git_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    if [ -n "$git_root" ] && [ -f "$git_root/pyproject.toml" ]; then
        echo "$git_root"; return 0
    fi
    local fallback="$HOME/.local/share/aiops-infra"
    if [ -f "$fallback/pyproject.toml" ]; then
        echo "$fallback"; return 0
    fi
    echo "ERROR: Cannot find aiops-infra repo root." >&2
    echo "Set AIOPS_INFRA_ROOT or ensure pyproject.toml exists." >&2
    return 1
}

_show_help() {
    local root
    root="$(_resolve_root 2>/dev/null || echo '<unresolved>')"
    cat <<HELP
Usage: conforma_run.sh <script-path> [args...]

Resolves the aiops-infra repo root and executes:
  python3 <repo-root>/<script-path> [args...]

Resolution chain (first match wins):
  1. ~/.conforma/.conforma-active/context.yaml -> aiops_infra_root
  2. \$AIOPS_INFRA_ROOT environment variable
  3. git rev-parse --show-toplevel
  4. ~/.local/share/aiops-infra (fallback)

Current repo root: $root

Examples:
  conforma_run.sh scripts/init_conforma_run.py "rhoai-3.5ea2"
  conforma_run.sh scripts/conforma_context_ops.py show
  conforma_run.sh skills/conforma-analyze/scripts/analyze_csv_report.py --help
HELP
    if [ "$root" != "<unresolved>" ] && [ -d "$root/scripts" ]; then
        echo ""
        echo "Available top-level scripts:"
        find "$root/scripts" -maxdepth 1 -name '*.py' ! -name '_*' -printf '  %f\n' 2>/dev/null | sort
    fi
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    _show_help; exit 0
fi
if [ "${1:-}" = "--version" ]; then
    md5sum "$0" | cut -d' ' -f1; exit 0
fi
if [ $# -eq 0 ]; then
    echo "ERROR: No script path given. Run with --help for usage." >&2
    exit 1
fi

_ROOT="$(_resolve_root)"
_SCRIPT="$_ROOT/$1"
if [ ! -f "$_SCRIPT" ]; then
    echo "ERROR: Script not found: $_SCRIPT" >&2
    exit 1
fi
shift
exec python3 "$_SCRIPT" "$@"
