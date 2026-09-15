#!/usr/bin/env bash
set -euo pipefail

# Enforce the link-work-to-jira skill's branch-linking state before commits.
# The skill hook is normally non-blocking, so this adapter turns its documented
# ACTION REQUIRED output into a pre-commit failure while preserving the skill's
# branch lookup and state-file conventions.

skill_dir="${LINK_WORK_TO_JIRA_SKILL_DIR:-${HOME}/.claude/skills/link-work-to-jira}"
check_script="$skill_dir/scripts/check-jira-state.sh"

if [[ ! -x "$check_script" ]]; then
    printf '%s\n' \
        "Commit blocked: link-work-to-jira skill script was not found or is not executable:" \
        "  $check_script" \
        "Install the skill or set LINK_WORK_TO_JIRA_SKILL_DIR to its directory." >&2
    exit 1
fi

project_dir=$(git rev-parse --show-toplevel 2>/dev/null) || {
    printf '%s\n' 'Commit blocked: unable to determine the repository root.' >&2
    exit 1
}

if ! output=$(
    CLAUDE_PROJECT_DIR="$project_dir" \
    CLAUDE_CODE_SESSION_ID= \
    bash "$check_script" < /dev/null
); then
    printf '%s\n' \
        'Commit blocked: link-work-to-jira branch validation failed.' \
        "$output" >&2
    exit 1
fi

if grep -qF 'ACTION REQUIRED' <<< "$output"; then
    printf '%s\n' \
        'Commit blocked: the current branch has no linked Jira ticket.' \
        'Link a Jira ticket to this branch with link-work-to-jira, then retry the commit.' >&2
    exit 1
fi
