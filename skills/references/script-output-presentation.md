# Script Output Presentation Rules

All conforma workflow scripts produce self-explanatory, user-facing output. The agent presents this output **verbatim** — never interpreting, summarizing, or reformatting the content. The rendering format depends on the output type.

## Plain-text output

Applies to: prerequisites check, `--format text` analysis, violation history, any script that outputs unstructured text.

- Present inside a fenced code block (gives monospace rendering + copy-to-clipboard in Cursor)
- A single 1-line contextual header is allowed above the block (e.g. "Prerequisites check failed:")
- No interpretation or rewording of the content inside the block

## Markdown-formatted output

Applies to: coverage table (`markdown_table` from JSON), resolution guide (`.md` file), `--format markdown` analysis.

- Render directly as markdown in the chat — tables, links, and headings display natively
- Do NOT wrap in a code block
- Still verbatim content — no rewording, no additions, no interpretation
- **File-based markdown** (e.g. resolution guide `.md`): the agent MUST read the file and then **copy the file content verbatim into the response text**. The Read tool returns content as agent context which may not be visible to the user — the content must appear as literal text in the agent's chat response to be rendered

## Terminology

All user-facing output (script strings, skill docs, agent responses) MUST use full terms — never abbreviations. This applies to both script code (print/log/label strings) and skill markdown.

| Wrong | Correct |
|-------|---------|
| MR, MRs | Merge Request, Merge Requests |
| PR, PRs | Pull Request, Pull Requests |
| rules (when referring to conforma violations) | violations |

**Hard rule**: When adding or editing user-facing strings in scripts or skill docs, always spell out the full term. Abbreviations are only acceptable in internal variable names (e.g. `prefetched_mrs`), log prefixes (e.g. `[Merge Requests]`), and code comments that are not rendered to the user.

## Hard constraints

- Agent MUST NOT compose, interpret, or summarize script output
- Agent MUST NOT add commentary or explanation after script output
- If output is not informative enough, the fix belongs in the script — not in LLM post-processing
- The only LLM-authored text allowed is the 1-line contextual header before the output
