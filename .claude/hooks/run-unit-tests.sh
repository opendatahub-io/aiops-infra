#!/bin/bash
# Stop hook: run unit tests when the agent finishes.
# If tests fail and this isn't already a retry, asks Claude to fix them.
# Works with both Claude Code and Cursor (same script, different config).

input=$(cat)
stop_hook_active=$(echo "$input" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("stop_hook_active", False))' 2>/dev/null)

if [ "$stop_hook_active" = "True" ]; then
  exit 0
fi

output=$(python3 -m pytest tests/unit/ -q --tb=short 2>&1)
exit_code=$?

if [ $exit_code -eq 0 ]; then
  exit 0
fi

printf '%s' "$output" | python3 -c '
import sys, json
output = sys.stdin.read()
msg = "Unit tests failed. Fix the failures and re-run the tests.\n\n```\n" + output + "\n```"
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": msg
    }
}))
'

exit 0
