---
name: conforma-docs
description: Full-text search across Conforma documentation, policy rules, exception process docs, and runbooks.
allowed-tools: Bash(python3:*),WebFetch
user-invocable: true
---

# Conforma Docs

Search Conforma documentation and runbooks. This skill provides full-text search across policy rules, exception process documentation, SKILL.md files from all conforma skills, and reference data.

## Quick Start

This skill is part of the conforma suite in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

**Setup:** See [README.md](README.md) for installation and prerequisites.

## Presentation Rules

All reference documents (`references/*.md`) in the conforma skill suite are pre-written for direct user presentation. The agent MUST follow these rules:

1. **Verbatim output** — copy the markdown content of the reference document into the response exactly as written. Do not rephrase, summarize, reorder, expand, or add commentary. The document IS the response.
2. **Diagrams** — Unicode box-drawing diagrams inside fenced code blocks MUST be copied character-for-character. Do not paraphrase, redraw, convert to bullet lists, or describe in prose. They are pre-rendered to display identically in Cursor chat, Claude Code terminal, and GitHub markdown.
3. **No unsolicited expansion** — if a section says "ask to learn more", do not expand it. Wait for the user to ask.
4. **No wrapping text** — do not add introductory sentences before or summary sentences after the copied content. The document starts and ends the response.

These rules apply to ALL reference document queries (overview, exception process, etc.). The only exception is rule-specific queries where the agent composes a response from upstream docs (see below).

## Source Routing

When the user asks a question, determine the query type and route to the correct source:

| Query type | Source | Action |
|------------|--------|--------|
| "What is conforma?", overview questions | `references/what-is-conforma.md` | Read the file, copy its content verbatim into the response |
| "Tell me more about violations/remedies/exceptions/release readiness" | `references/what-is-conforma-details.md` | Read the file, copy the requested section verbatim (or the full file if the user asks about all concepts) |
| Specific rule lookup ("What does X rule mean?") | Upstream docs via `conforma-release-policy-rules.yaml` | Follow the rule-specific query workflow below |
| Exception process, how to create exceptions | `search_docs.py` | Run search, present matching reference doc content verbatim |
| General keyword search | `search_docs.py` | Run search, present matching reference doc content verbatim |

## Workflow

### Overview queries

When the user asks "what is conforma" or similar overview questions:

1. Read `references/what-is-conforma.md` (relative to this skill's directory)
2. Copy its full markdown content into the response. Do not add, remove, or rephrase anything.

### Concept detail queries

When the user asks for more detail on violations, remedies, exceptions, or release readiness (following up on the overview's "ask about any of these concepts"):

1. Read `references/what-is-conforma-details.md` (relative to this skill's directory)
2. Copy the requested section(s) verbatim. If the user asks about a single concept (e.g. "tell me more about violations"), copy only that `##` section. If the user asks about all concepts, copy the full file.

### Rule-specific queries

When the user asks about a specific Conforma policy rule, this is the one case where the agent composes a response (because content comes from an external source):

1. **Look up the rule** in `conforma-exception/references/conforma-release-policy-rules.yaml` to find the rule entry and its `docs:` URL
2. **Fetch upstream docs** via WebFetch using the `docs:` URL (e.g., `https://conforma.dev/docs/policy/packages/release_hermetic_task.html`)
3. **Compose the response** using this exact three-part structure:

   **Part 1 — Rule summary** (2-3 sentences from the upstream doc's description): what the rule checks and why it matters.

   **Part 2 — Failure message** (verbatim from upstream doc): the exact violation message the user would see, inside a fenced code block.

   **Part 3 — Resolution** (from upstream doc's solution/resolution section): the specific fix, with a code example if the upstream doc provides one.

4. Do not add product-specific commentary, opinions, or extra context beyond what the upstream doc provides.

**Fallback**: if the upstream fetch fails (offline, VPN issues), respond with exactly: the rule `code` and `name` from the local YAML catalog, and the statement "Full documentation is available at `<docs URL>`."

### Keyword search

For general queries, run the search script:

```bash
python3 skills/conforma-docs/scripts/search_docs.py --query "hermetic build"
python3 skills/conforma-docs/scripts/search_docs.py --query "rpm signing key" --format json
```

The script auto-discovers and indexes content from all `skills/conforma*/` directories:
- `references/` — markdown and YAML reference data
- `docs/` — additional documentation
- `SKILL.md` — skill definitions (prose only, frontmatter and code blocks stripped)

When presenting search results: if a result points to a reference document, read that document and copy the relevant section verbatim. Do not paraphrase search result snippets into a new summary.

## Content Boundaries

This skill does NOT own exception-related content. All exception documentation (what exceptions are, how to create them, the approval workflow) belongs to the `conforma-exception` skill and its `references/` directory. Since `search_docs.py` indexes all conforma skills, exception queries will surface the right content automatically.

## Reference Data

This skill indexes content from across the conforma skill suite:
- `conforma-docs/references/what-is-conforma.md` — product-agnostic Conforma overview
- `conforma-docs/references/what-is-conforma-details.md` — detailed concept explanations (violations, remedies, exceptions, release readiness) with examples
- `conforma-exception/references/conforma-release-policy-rules.yaml` — all policy rules with codes, names, and upstream doc URLs
- `conforma-exception/references/conforma-exception-overview.md` — what exceptions are
- `conforma-exception/references/exception-process.md` — exception request workflow
- `conforma-exception/references/policy-files.yaml` — GitLab policy file path mappings
- All `conforma*/SKILL.md` files — domain context from each skill

## Examples

- "What is conforma?" — read `references/what-is-conforma.md`, copy verbatim
- "What does hermetic_task.hermetic mean?" — look up rule, fetch upstream docs, compose three-part response
- "How do I create an exception?" — search finds `conforma-exception/references/exception-process.md`, copy relevant section verbatim
- "What are the allowed RPM signing keys?" — search policy rules catalog, compose three-part response
- "What is the violations-first philosophy?" — search finds it in `conforma-analyze/SKILL.md`, copy relevant section verbatim
