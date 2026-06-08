---
name: conforma-docs
description: Full-text search across Conforma documentation, policy rules, exception process docs, and runbooks.
allowed-tools: Bash(python3:*)
user-invocable: true
---

# Conforma Docs

Search Conforma documentation and runbooks. This skill provides full-text search across policy rules, exception process documentation, SKILL.md files from all conforma skills, and reference data.

## Quick Start

This skill is part of the conforma suite in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

**Install all conforma skills** (via skills-registry):
- Cursor: `cursor skills install opendatahub-io/aiops-infra`
- Claude Code: `claude install-skill opendatahub-io/aiops-infra`

## Mandatory Presentation Format

Every answer produced by this skill MUST follow the **theory / example / explanation** structure for each concept or section. No exceptions.

### Template

For each concept in the response:

1. **Brief theory** (2-3 sentences) — what it is, why it matters
2. **Example** — a real code snippet, YAML fragment, CLI output, or violation message
3. **Explanation of the example** — walk through what each part means, connecting back to the theory

### Worked example

If a user asks "What does hermetic_task.hermetic mean?", the response must look like:

> **Hermetic builds** ensure that a Tekton task runs without network access during the build step. This prevents the build from fetching undeclared dependencies at runtime, guaranteeing that everything the build needs is pre-fetched and accounted for in the SBOM.
>
> ```
> Task 'buildah' was not invoked with the hermetic parameter set
> ```
>
> This violation message appears when a build task (here `buildah`) ran without `HERMETIC=true`. The Conforma policy engine checked the PipelineRun attestation and found the task's `HERMETIC` parameter was either missing or set to `false`. To resolve this, add `HERMETIC: "true"` to the task's params in your PipelineAs-Code definition.

## Source Routing

When the user asks a question, determine the query type and use the appropriate source:

| Query type | Source | How |
|------------|--------|-----|
| "What is conforma?", overview questions | Local reference | Read `references/what-is-conforma.md` and present following the mandatory format |
| Specific rule lookup ("What does X rule mean?") | Upstream docs | Look up the rule in `conforma-release-policy-rules.yaml` (in conforma-exception/references/), get the `docs:` URL, fetch via WebFetch, present in the mandatory format |
| Exception process, how to create exceptions | Cross-skill search | Run `search_docs.py --query "..."` — it indexes conforma-exception/references/ which has comprehensive exception docs |
| General keyword search | Full-text search | Run `search_docs.py --query "..."` to search across all conforma skills |

## Workflow

### Overview queries

When the user asks "what is conforma" or similar overview questions:

1. Read `references/what-is-conforma.md` (relative to this skill's directory)
2. Present the content following the mandatory presentation format

### Rule-specific queries

When the user asks about a specific Conforma policy rule:

1. **Look up the rule** in `conforma-exception/references/conforma-release-policy-rules.yaml` to find the rule entry and its `docs:` URL
2. **Fetch upstream docs** via WebFetch using the `docs:` URL (e.g., `https://conforma.dev/docs/policy/packages/release_hermetic_task.html`)
3. **Present in the mandatory format**: use the upstream content (rule description, solution text, failure message) as the basis, then wrap with RHOAI context

**Fallback**: if the upstream fetch fails (offline, VPN issues), use the rule `name` and `code` from the local YAML catalog and note that full details are available at the `docs:` URL.

### Keyword search

For general queries, use the search script:

```bash
python3 skills/conforma-docs/scripts/search_docs.py --query "hermetic build"
python3 skills/conforma-docs/scripts/search_docs.py --query "rpm signing key" --format json
```

The script auto-discovers and indexes content from all `skills/conforma*/` directories:
- `references/` — markdown and YAML reference data
- `docs/` — additional documentation
- `SKILL.md` — skill definitions (prose only, frontmatter and code blocks stripped)

## Content Boundaries

This skill does NOT own exception-related content. All exception documentation (what exceptions are, how to create them, the approval workflow) belongs to the `conforma-exception` skill and its `references/` directory. Since `search_docs.py` indexes all conforma skills, exception queries will surface the right content automatically.

## Reference Data

This skill indexes content from across the conforma skill suite:
- `conforma-docs/references/what-is-conforma.md` — RHOAI-contextualized Conforma overview
- `conforma-exception/references/conforma-release-policy-rules.yaml` — all policy rules with codes, names, and upstream doc URLs
- `conforma-exception/references/conforma-exception-overview.md` — what exceptions are
- `conforma-exception/references/exception-process.md` — RHOAI exception request workflow
- `conforma-exception/references/policy-files.yaml` — GitLab policy file path mappings
- All `conforma*/SKILL.md` files — domain context from each skill

## Examples

- "What is conforma?" — read `references/what-is-conforma.md`, present with theory/example/explanation
- "What does hermetic_task.hermetic mean?" — look up rule, fetch upstream docs, present in mandatory format
- "How do I create an exception?" — search indexes conforma-exception's references
- "What are the allowed RPM signing keys?" — search policy rules catalog
- "What is the violations-first philosophy?" — search finds it in conforma-analyze's SKILL.md
