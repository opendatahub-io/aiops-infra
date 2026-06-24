#!/bin/bash
# Runs unit tests when the agent finishes.
# If tests fail, signals the agent to fix them.
#
# Platform-agnostic: detects Cursor vs Claude Code hook format automatically.
# Both .cursor/hooks.json and .claude/settings.json point here.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Platform detection ---
# Claude Code pipes JSON to stdin; Cursor does not.
# Use timeout on read to avoid blocking when stdin is a pipe with no data.
PLATFORM="cursor"
STDIN_DATA=""
if [ ! -t 0 ]; then
    STDIN_DATA=$(timeout 1 cat 2>/dev/null || true)
    if [ -n "$STDIN_DATA" ] && echo "$STDIN_DATA" | python3 -c 'import sys,json; json.load(sys.stdin)' 2>/dev/null; then
        PLATFORM="claude"
        stop_active=$(echo "$STDIN_DATA" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("stop_hook_active", False))' 2>/dev/null || echo "False")
        if [ "$stop_active" = "True" ]; then
            exit 0
        fi
    fi
fi

# --- Run tests ---
cd "$REPO_ROOT"
output=$(python3 -m pytest tests/unit/ -q --tb=short 2>&1) || true
exit_code=${PIPESTATUS[0]:-$?}

if [ $exit_code -eq 0 ]; then
    if [ "$PLATFORM" = "cursor" ]; then
        echo '{"decision": "stop"}'
    fi
    exit 0
fi

# --- Report failures ---
MESSAGE="Unit tests failed. Fix the failures and re-run the tests.\n\n\`\`\`\n${output}\n\`\`\`"

if [ "$PLATFORM" = "cursor" ]; then
    printf '%s' "$MESSAGE" | python3 -c '
import sys, json
msg = sys.stdin.read()
print(json.dumps({"decision": "continue", "followup_message": msg}))
'
else
    printf '%s' "$MESSAGE" | python3 -c '
import sys, json
msg = sys.stdin.read()
print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": msg}}))
'
fi

exit 0
