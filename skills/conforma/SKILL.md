---
name: conforma
description: Single entry point for all Conforma-related queries. Routes user intent to the appropriate atomic conforma skill.
allowed-tools: Bash(python3:*,gh:*,glab:*,acli:*,git:*)
user-invocable: true
---

# Conforma

Single entry point for all Conforma-related queries. Detect the user's intent and route to the appropriate atomic skill.

## Quick Start

This skill is part of the conforma suite in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

**Install all conforma skills** (via skills-registry):
- Cursor: `cursor skills install opendatahub-io/aiops-infra`
- Claude Code: `claude install-skill opendatahub-io/aiops-infra`

**Prerequisites** (CLI tools -- install once):
- `glab` -- GitLab CLI ([install](https://gitlab.com/gitlab-org/cli/-/releases))
- `acli` -- Jira CLI
- `gh` -- GitHub CLI ([install](https://cli.github.com))

Python dependencies are auto-installed on first run.

## Intent Routing

Detect the user's intent from their query and route to the appropriate skill. Match against the keywords/phrases in the left column. If the intent is ambiguous, ask the user to clarify.

| Intent keywords | Route to |
|-----------------|----------|
| violations, scan, status, what's failing, conforma report, violation report, fetch violations | use the **conforma-analyze** skill |
| fetch tekton report, fetch pipelinerun, EC report, raw report JSON | use the **conforma-report-fetch** skill (Tekton JSON mechanism) |
| create exception, new exception, extend exception, waive, add exception | use the **conforma-exception** skill |
| expired, manage exceptions, assess exceptions, cleanup, action loop | use the **conforma-exception** skill (with `--assess-expired` or `--find-expired` mode) |
| fix, remedy, resolve, patch, code change | use the **conforma-remedy** skill |
| docs, documentation, search docs, runbook, policy rules, what is conforma | use the **conforma-docs** skill |
| ship, release, readiness, gate, can we ship, blocking, go/no-go | use the **conforma-release-readiness** skill |
| gitlab auth, gitlab token, glab login, glab auth | use the **gitlab-auth** skill |
| jira auth, acli auth, jira login, jira token | use the **jira-auth** skill |
| github auth, gh auth, github token | use the **github-auth** skill |

## Routing Rules

1. **Always route — never execute directly.** This skill does not run any scripts itself. It exists solely to identify which atomic skill should handle the user's request.

2. **Prefer the most specific skill.** If the user asks about violations AND wants to create an exception, first route to `conforma-analyze` to get the violation data, then route to `conforma-exception` to create the exception.

3. **Violations-first philosophy.** When a user mentions a violation, always start with `conforma-analyze` to understand the current state before suggesting exception creation. Exceptions are a last resort.

4. **Auth issues take priority.** If the user reports an auth error or a skill fails with an auth-related error, route to the appropriate auth skill first.

5. **Ambiguous queries.** If the user's intent matches multiple skills equally, ask them to clarify. Example: "I need help with conforma" could mean analyze, exception, or docs.

## Example Queries

- "Show me the current violations for rhoai-3.5" → **conforma-analyze**
- "Create an exception for hermetic_task.hermetic" → **conforma-exception**
- "What expired exceptions do we have?" → **conforma-exception** (manage mode)
- "Can rhoai-3.5 ship?" → **conforma-release-readiness**
- "What does the hermetic build rule mean?" → **conforma-docs**
- "My gitlab auth isn't working" → **gitlab-auth**
- "Fix the prefetch-dependencies violation in model-registry" → **conforma-remedy**
