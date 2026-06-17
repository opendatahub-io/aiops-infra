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

**Setup:** See [README.md](README.md) for installation and prerequisites.

## Intent Routing

Detect the user's intent from their query and route to the appropriate skill. Match against the keywords/phrases in the left column. If the intent is ambiguous, ask the user to clarify.

| Intent keywords | Route to |
|-----------------|----------|
| violations, scan, status, what's failing, conforma report, violation report, fetch violations | use the **conforma-analyze** skill |
| fetch tekton report, fetch pipelinerun, EC report, raw report JSON | use the **conforma-report-fetch** skill (Tekton JSON mechanism) |
| create exception, new exception, extend exception, waive, add exception | use the **conforma-exception** skill |
| expired, manage exceptions, assess exceptions, cleanup, action loop | use the **conforma-exception** skill (with `--assess-expired` or `--find-expired` mode) |
| fix, remedy, resolve, patch, code change, troubleshoot, diagnose, why is this failing, how to fix | use the **conforma-remedy** skill |
| docs, documentation, search docs, runbook, policy rules, what is conforma | use the **conforma-docs** skill |
| ship, release, readiness, gate, can we ship, blocking, go/no-go | use the **conforma-release-readiness** skill |
| catalog, component mapping, jira component, software catalog, which team owns | use the **software-catalog-query** skill |
| search open MRs, find exception MRs, list MRs | use the **search-conforma-open-exception-mrs** skill |
| MR coverage, does MR cover, MR components | use the **analyze-mr-component-coverage** skill |
| search jira tickets, conforma-violation tickets, open tickets | use the **search-conforma-jira-tickets** skill |
| search slack, slack threads, slack discussions | use the **search-conforma-slack-threads** skill |
| search existing exceptions, policy exceptions, find exceptions | use the **search-conforma-existing-exceptions** skill |
| check coverage, exception coverage, gate check | use the **check-exception-coverage** skill |
| report bug, file issue, something is broken, skill feedback, report problem, conforma-feedback | use the **conforma-feedback** skill |
| gitlab auth, gitlab token, glab login, glab auth | use the **gitlab-auth** skill |
| jira auth, acli auth, jira login, jira token | use the **jira-auth** skill |
| github auth, gh auth, github token | use the **github-auth** skill |
| slack auth, slack token, slack search | use the **slack-auth** skill |

## Routing Rules

1. **Always route — never execute directly.** This skill does not run any scripts itself. It exists solely to identify which atomic skill should handle the user's request.

2. **Prefer the most specific skill.** If the user asks about violations AND wants to create an exception, first route to `conforma-analyze` to get the violation data, then route to `conforma-exception` to create the exception.

3. **Violations-first philosophy.** When a user mentions a violation, always start with `conforma-analyze` to understand the current state before suggesting exception creation. If the violation is fixable at the code level (consult [`skills/references/violation-catalog.yaml`](references/violation-catalog.yaml) for classification), route to `conforma-remedy` first. Exceptions are a last resort.

4. **Auth issues take priority.** If the user reports an auth error or a skill fails with an auth-related error, route to the appropriate auth skill first.

5. **Ambiguous queries.** If the user's intent matches multiple skills equally, ask them to clarify. Example: "I need help with conforma" could mean analyze, exception, or docs.

6. **No custom analysis — HARD FAILURE.** When a conforma report/violation analysis is requested, the agent MUST follow the full deterministic workflow in `conforma-analyze`. The agent MUST NEVER produce ad-hoc summaries, run scripts with shortcuts (e.g. `--csv` directly, `| head`), skip workflow steps, or manually interpret CSV data. If only existence is asked, answer that and ask whether to run the full analysis. Partial or improvised analysis output is a hard failure.

## Example Queries

- "Show me the current violations for rhoai-3.5" → **conforma-analyze**
- "What is conforma status for rhoai-3.5-ea.1?" → **conforma-analyze**
- "Create an exception for hermetic_task.hermetic" → **conforma-exception**
- "What expired exceptions do we have?" → **conforma-exception** (manage mode)
- "Can rhoai-3.5 ship?" → **conforma-release-readiness**
- "What does the hermetic build rule mean?" → **conforma-docs**
- "My gitlab auth isn't working" → **gitlab-auth**
- "Fix the prefetch-dependencies violation in model-registry" → **conforma-remedy**
- "Why is model-registry failing the hermetic check?" → **conforma-remedy**
- "How do I fix the untrusted task violation?" → **conforma-remedy**
- "What Jira component is odh-dashboard?" → **software-catalog-query**
- "Which team owns the vllm component?" → **software-catalog-query**
- "The conforma-exception skill crashed when creating an MR" → **conforma-feedback**
- "I want to report a bug in the analyze skill" → **conforma-feedback**
