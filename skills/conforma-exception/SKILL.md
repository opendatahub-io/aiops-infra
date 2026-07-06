---
name: conforma-exception
description: Manage RHOAI Conforma exceptions end-to-end — create, extend, check, and reconcile policy exceptions. Uses a three-ticket Jira model (Violation Report, Remediation, Approval) with prod/stage environment support. Handles ProdSec form, OCPEXCEPT Jira, GitLab Merge Requests in konflux-release-data, deduplication, and cross-linking.
allowed-tools: Bash(python3:*,acli:*,glab:*,git:*,docker:*,podman:*)
user-invocable: true
---

# Conforma Exception Management

This skill manages RHOAI Conforma exceptions. Route to the appropriate workflow:

| Intent | Workflow file |
|--------|---------------|
| Create a new exception | Read `workflows/create.md` |
| Extend an existing exception | Read `workflows/extend.md` |
| Manage lifecycle (reconcile, deduplicate) | Read `workflows/lifecycle.md` |
| Check/search exceptions | Read `workflows/check.md` |
| Assess expired exceptions | Read `workflows/assess-expired.md` |

## Violations-First Philosophy

**Conforma exceptions are a last resort, not the default resolution path.** When a violation is detected, the primary goal is to fix the underlying issue in the component code (e.g., enable hermetic builds, use signed RPMs, fix failing tests). An exception should only be created when a code fix is genuinely not feasible within the release timeline.

When presenting violations to the user:
- Frame next steps in terms of resolving the violation first
- Only suggest creating an exception when there's evidence the violation cannot be fixed in code (e.g., third-party RPM signing keys that Red Hat cannot control, upstream dependencies with known timelines)
- Never present "create exception" as the default or first-choice action for new violations without existing artifacts
- Consult [`skills/references/violation-catalog.yaml`](../references/violation-catalog.yaml) for the `exception_context.when_to_exception` field to determine if an exception is appropriate for the given violation type
- For violations with `classification.resolution_path: code_fix`, redirect to the **conforma-remedy** skill first

## Naming Conventions

- **Never use the word "product"** in variable names, environment variables, config keys, or code concepts within this skill. The term is too vague and overloaded.
- Use **`application_slug`** when referring to the identifier that selects which set of policy files belongs to the current application (e.g. `rhoai` in `registry-rhoai-prod.yaml`).
- Environment variable: `KONFLUX_APPLICATION_SLUG`. Site-config key: `application_slug`.
- If the application slug is unavailable and multiple policy files match a generic pattern, the agent MUST ask the user to choose — never silently pick one.


## Error Handling

Each script validates inputs and exits non-zero on failure. The orchestrator stops at the first failure, preserving partial results in the output JSON. Common errors:

- Invalid RHOAI version format
- Component name / version mismatch
- `--effective-until` not a future date
- `acli` or `glab` not authenticated
- GitLab Merge Request creation failure (permissions, branch conflict)
- Jira ticket creation failure (permissions, invalid project)
- Verification failure (labels, links, or fields not confirmed after retries)


## Pipeline Mode (Handover)

For backward compatibility with the `conforma-troubleshooter` agent, the orchestrator also accepts `--output` to write structured JSON results compatible with the handover document format.

## Reference Documentation

See `references/exception-process.md` for the full process documentation including:
- Jira project routing rules
- Senior manager approval requirements
- VolatileCriteria schema
- Upstream reference links (Konflux docs, ProdSec Confluence, conforma.dev)

See `references/conforma-release-policy-rules.yaml` for the complete catalog of enforced rules in the Conforma `redhat` collection, sourced from [conforma.dev/docs/policy/release_policy.html](https://conforma.dev/docs/policy/release_policy.html). Each entry includes the rule code, human-readable name, and documentation URL. Use this catalog to validate `--rule` values and provide context when handling non-templated ("other" category) exceptions.

