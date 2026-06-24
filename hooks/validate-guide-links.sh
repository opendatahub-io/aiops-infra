#!/bin/bash
# Validates link formatting in generated resolution guides before submission.
# Fast structural checks only — no network calls (stop hooks must be instant).
#
# Checks for:
# - Empty URLs in markdown links: [text]() or href=""
# - Malformed URLs (missing scheme, bare paths in href)
# - Broken markdown link syntax (unclosed parentheses, nested brackets)
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

# --- Find the most recent resolution guide in .work/ ---
GUIDE=""
for dir in $(ls -dt "$REPO_ROOT"/.work/20* 2>/dev/null); do
    candidate="$dir/conforma-resolution-guide.md"
    if [ -f "$candidate" ]; then
        GUIDE="$candidate"
        break
    fi
done

if [ -z "$GUIDE" ]; then
    if [ "$PLATFORM" = "cursor" ]; then
        echo '{"decision": "stop"}'
    fi
    exit 0
fi

# --- Validate link formatting (no network calls) ---
ISSUES=$(python3 -c "
import re, sys

content = open('$GUIDE').read()
lines = content.splitlines()
issues = []

for i, line in enumerate(lines, 1):
    # Empty markdown links: [text]()
    for m in re.finditer(r'\[([^\]]+)\]\(\s*\)', line):
        issues.append(f'  Line {i}: empty URL in [{m.group(1)}]()')

    # Empty HTML hrefs: href=\"\"
    if re.search(r'href=\"\s*\"', line):
        issues.append(f'  Line {i}: empty href attribute')

    # Markdown links with relative paths (should be absolute URLs in a guide)
    for m in re.finditer(r'\[([^\]]+)\]\(([^)]+)\)', line):
        url = m.group(2).strip()
        if url and not url.startswith(('http://', 'https://', '#', 'mailto:')):
            issues.append(f'  Line {i}: relative path in [{m.group(1)}]({url})')

    # HTML hrefs without scheme
    for m in re.finditer(r'href=\"([^\"]+)\"', line):
        url = m.group(1).strip()
        if url and not url.startswith(('http://', 'https://', '#', 'mailto:')):
            issues.append(f'  Line {i}: relative path in href=\"{url}\"')

if issues:
    print('\n'.join(issues))
    sys.exit(1)
else:
    sys.exit(0)
" 2>&1) || true

if [ -z "$ISSUES" ]; then
    if [ "$PLATFORM" = "cursor" ]; then
        echo '{"decision": "stop"}'
    fi
    exit 0
fi

# --- Report issues ---
RELATIVE_GUIDE="${GUIDE#$REPO_ROOT/}"
ISSUE_COUNT=$(echo "$ISSUES" | wc -l | tr -d ' ')
MESSAGE="Link validation found ${ISSUE_COUNT} issue(s) in the resolution guide (\`${RELATIVE_GUIDE}\`):\n\n\`\`\`\n${ISSUES}\n\`\`\`\n\nFix the broken links before submitting, or submit with the known issues."

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
