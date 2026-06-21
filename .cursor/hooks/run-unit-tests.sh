#!/bin/bash
# Run unit tests when the agent finishes.
# Returns a followup_message if any tests fail so the agent can fix them.

output=$(python3 -m pytest tests/unit/ -q --tb=short 2>&1)
exit_code=$?

if [ $exit_code -eq 0 ]; then
  echo '{"decision": "stop"}'
else
  printf '%s' "$output" | python3 -c '
import sys, json
output = sys.stdin.read()
msg = "Unit tests failed. Fix the failures and re-run the tests.\n\n```\n" + output + "\n```"
print(json.dumps({"decision": "continue", "followup_message": msg}))
'
fi

exit 0
