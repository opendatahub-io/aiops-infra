#!/bin/bash
# Session-start hook: check for pending preference proposals.
# If proposals exist, inject a followup_message to surface them to the user.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo ".")"
PROPOSALS="$REPO_ROOT/.work/proposed-conventions.yaml"

if [ -f "$PROPOSALS" ] && [ -s "$PROPOSALS" ]; then
  COUNT=$(grep -c "^  - category:" "$PROPOSALS" 2>/dev/null || echo 0)
  if [ "$COUNT" -gt 0 ]; then
    cat <<EOF
{"decision": "continue", "followup_message": "There are $COUNT pending user coding preference proposals in .work/proposed-conventions.yaml discovered from recent sessions. Please read the file and present each proposal to the user for confirmation. For confirmed proposals, append them to the appropriate section in AGENTS.md and remove them from the proposals file."}
EOF
  else
    echo '{"decision": "stop"}'
  fi
else
  echo '{"decision": "stop"}'
fi
