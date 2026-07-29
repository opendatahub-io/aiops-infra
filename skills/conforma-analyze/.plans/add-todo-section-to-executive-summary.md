# Plan: Add TODO Section to Conforma Executive Summary

**Jira**: [RHAIENG-6190](https://redhat.atlassian.net/browse/RHAIENG-6190)

## Context

The conforma-analyze executive summary currently leads with a **Context Confirmation** metadata table (release, dates, policy files, CSV source), followed by the Executive Summary tables (Tables 1–5), tooling health warnings, and summary metrics. For an engineer or AI agent opening this report, the most actionable information — *what work is needed?* — is buried below metadata.

The goal is to add a concise **TODO** section at the very top of the executive summary, rendered as a numbered table with a checkbox column, so the reader immediately sees what actions are required.

Additionally, `render_key_takeaways()` contains nested helper functions and duplicated data-gathering logic that should be extracted for reuse. This plan addresses both the new TODO section and the necessary refactoring.

## Proposed Architecture

```
                    ┌──────────────────────────────────┐
                    │  generate_resolution_guide.py     │
                    │  main() → generate_resolution_guide()
                    └──────────┬───────────────────────┘
                               │ calls
                    ┌──────────▼───────────────────────┐
                    │  guide_renderers.py                │
                    │                                    │
                    │  _compute_violation_buckets()      │◄── NEW: shared data extraction
                    │      ▲              ▲              │
                    │      │              │              │
                    │  render_todo()   render_key_       │
                    │  (NEW)           takeaways()       │
                    │      │          (REFACTORED)       │
                    │      │              │              │
                    │      ▼              ▼              │
                    │  _find_covering_mr()  ◄─────────── │── EXTRACTED to module-level
                    │  _violation_count()   ◄─────────── │── EXTRACTED to module-level
                    │                                    │
                    └──────────┬───────────────────────┘
                               │ writes
                    ┌──────────▼───────────────────────┐
                    │  write_executive_summary()         │
                    │                                    │
                    │  Section order (CHANGED):          │
                    │  1. todo          ◄── NEW          │
                    │  2. metadata_header                │
                    │  3. key_takeaways                  │
                    │  4. tooling_health                 │
                    │  5. summary_metrics                │
                    │  6. detailed_documents             │
                    └──────────────────────────────────┘

    Full resolution guide: unchanged (no TODO section)
    Executive summary file: TODO section prepended
    context.yaml: no schema changes (TODO is derived, not stored)
```

*Diagram is proposed in this document and reflects the implementation below.*

## Approach

### 0. Rename `## Executive Summary` → `## Violations Breakdown`

The Tables 1–5 section in `render_key_takeaways()` is currently titled `## Executive Summary` (line 224 of guide_renderers.py). With the new TODO section serving as the true top-level summary, rename this heading to `## Violations Breakdown` to accurately reflect its content (detailed violation-by-violation breakdown grouped by coverage status).

Update the heading in `render_key_takeaways()` and all references:
- [guide_renderers.py:224](skills/conforma-analyze/scripts/guide_renderers.py#L224): `lines = ["## Violations Breakdown", ""]`
- [conforma/SKILL.md:75](skills/conforma/SKILL.md#L75): Change `"Executive Summary" not "Key Takeaways"` to `"Violations Breakdown" not "Executive Summary" or "Key Takeaways"`
- [conforma/SKILL.md:84](skills/conforma/SKILL.md#L84): Update ordering rule (combined with step 6)
- Any test assertions that check for `"## Executive Summary"` in the rendered output

### 1. Extract shared helpers from `render_key_takeaways()` to module-level

In [guide_renderers.py](skills/conforma-analyze/scripts/guide_renderers.py), three helpers are currently nested closures inside `render_key_takeaways()` (lines 237–262). Extract them to module-level so both `render_key_takeaways()` and the new `render_todo()` can call them:

- **`_find_covering_mr(mrs, component)`** (line 251) — no closure deps, extract as-is
- **`_violation_count(rule, component, by_component_rule)`** (line 257) — add `by_component_rule` parameter instead of closure
- `_format_violation_cell` stays nested — it depends on `detail_lookup`/`detail_labels` which are only needed by the detailed tables, not by TODO

### 2. Extract shared data-gathering into `_compute_violation_buckets()`

The logic at lines 264–448 of `render_key_takeaways()` classifies violations into buckets (no-exception-no-MR, expiring-no-MR, expiring-MR-insufficient, expiring-MR-sufficient, has-MR). This exact data is needed by both `render_key_takeaways()` and `render_todo()`.

Extract into a new module-level function:

```python
def _compute_violation_buckets(
    coverage_data: dict,
    analysis_result: analysis.AnalysisResult,
    by_component_rule: dict[tuple[str, str], int],
    upcoming_release_date: str = "",
) -> dict:
    """Classify violations into action-priority buckets.

    Returns dict with keys: no_mr_entries, has_mr_entries, expiring_no_mr,
    expiring_mr_insufficient, expiring_mr_sufficient, covered_violations,
    not_covered_violations, total_violations, coverage_pct.
    """
```

Both `render_key_takeaways()` and `render_todo()` call this function instead of duplicating the classification logic.

### 3. New renderer: `render_todo()` in [guide_renderers.py](skills/conforma-analyze/scripts/guide_renderers.py)

A new function that produces a compact numbered table with a checkbox column. Items are auto-discovered from the data — no hardcoded category list:

```python
def render_todo(
    coverage_data: dict,
    analysis_result: analysis.AnalysisResult,
    by_component_rule: dict[tuple[str, str], int],
    tooling_health_data: dict | None = None,
    upcoming_release_date: str = "",
) -> str:
```

Output format (table with checkbox column — confirmed by user). Each TODO item links to the corresponding table/section anchor in the Executive Summary below:

```markdown
## TODO

> **4 actions** required — 12 violations need attention

| # | Action | Violations | Done |
|--:|--------|:----------:|:----:|
| 1 | [**Fix or add exceptions**](#table-1) — no coverage or open MR | 4 | [ ] |
| 2 | [**Create MRs**](#table-2) — exceptions expiring before release, no MR | 3 | [ ] |
| 3 | [**Extend exception dates**](#table-3) — MR exception expires before release | 2 | [ ] |
| 4 | [**Track and merge**](#table-5) open MRs | 5 | [ ] |
```

**Anchor linking**: `render_key_takeaways()` currently renders table headings as `- **Table {n}.** — ...` with no HTML anchor. Add an `<a id="table-{n}"></a>` anchor before each table heading so the TODO links resolve. Example:

```python
# In render_key_takeaways(), before each table heading:
lines.append(f'<a id="table-{table_num}"></a>')
lines.append(f"- **Table {table_num}.** — **{count:,} violations ...**:")
```

Similarly, add anchors for non-table sections referenced by TODO rows:
- `<a id="tooling-health"></a>` before the tooling health section
- `<a id="expiring-exceptions"></a>` before the expiring exceptions bullet
- `<a id="warnings-becoming-violations"></a>` before the warnings bullet

Auto-discovery rules — each row is only emitted when data exists (non-zero count):
- **Bucket `no_mr_entries`** → "Fix or add exceptions" row, links to `#table-1`
- **Bucket `expiring_no_mr`** → "Create MRs" row, links to `#table-2`
- **Bucket `expiring_mr_insufficient`** → "Extend exception dates" row, links to `#table-3`
- Table 4 (expiring with sufficient MR) is omitted — low risk, MR already covers release
- **Bucket `has_mr_entries`** → "Track and merge" row, links to `#table-5`
- **Unhealthy tooling** → extra row linking to `#tooling-health`: "**Investigate tooling** — `<names>` workflow failing, data may be stale"
- **Expiring exceptions within 14 days** → extra row linking to `#expiring-exceptions`
- **Warnings becoming violations** → extra row linking to `#warnings-becoming-violations`

The blockquote summary line auto-counts the numbered rows and sums violation counts.

If all buckets are empty and tooling is healthy → return `"## TODO\n\n> No actions required — all violations are covered\n"`.

### 4. Update `write_executive_summary()` signature and section ordering

In [guide_renderers.py:1170](skills/conforma-analyze/scripts/guide_renderers.py#L1170):

- Add `todo: str` parameter
- Change sections list from `[metadata_header, key_takeaways, tooling_health, summary_metrics]` to `[todo, metadata_header, key_takeaways, tooling_health, summary_metrics]`

### 5. Update `generate_resolution_guide()` caller

In [generate_resolution_guide.py](skills/conforma-analyze/scripts/generate_resolution_guide.py) around line 274:

- Call `render_todo()` with the same data already available (`coverage_data`, `analysis_result`, `counts.by_component_rule`, `tooling_health_data`, `upcoming_release_date`)
- Pass the result to `_write_executive_summary()` as the new `todo` parameter
- The full resolution guide section list (line 277) remains unchanged — TODO is executive-summary-only

### 6. Update documentation

- **[conforma/SKILL.md](skills/conforma/SKILL.md) line 75**: Change `"Executive Summary" not "Key Takeaways"` to `"Violations Breakdown" not "Executive Summary" or "Key Takeaways"`
- **[conforma/SKILL.md](skills/conforma/SKILL.md) line 84**: Change "Reports must have Executive Summary above main table" to "Reports must have TODO above Context Confirmation, followed by Violations Breakdown above main table"
- **[conforma/TODO.md](skills/conforma/TODO.md)**: Add a new done item referencing this plan, commit, and Jira ticket
- **Plan file**: Copy this plan to `skills/conforma-analyze/.plans/` as part of the implementation commit

### 7. Unit tests

Add tests in [tests/unit/test_conforma_analyze_generate_resolution_guide.py](tests/unit/test_conforma_analyze_generate_resolution_guide.py):

**New test class `TestRenderTodo`:**
- `test_todo_all_buckets_populated` — all action rows appear when all buckets have data
- `test_todo_empty_buckets_omitted` — rows with zero violations don't appear
- `test_todo_no_actions_required` — returns "No actions required" when all violations covered
- `test_todo_table_header_format` — validates the markdown table header matches expected columns
- `test_todo_violation_counts_accurate` — counts in the table match the source data
- `test_todo_tooling_unhealthy_row` — tooling health warning row appears when tools are unhealthy
- `test_todo_tooling_healthy_no_row` — no tooling row when all tools healthy
- `test_todo_expiring_exceptions_row` — expiring exceptions warning row appears
- `test_todo_warnings_becoming_violations_row` — warnings row appears
- `test_todo_summary_line_counts` — blockquote counts match the number of rows
- `test_todo_table4_omitted` — Table 4 (sufficient MR) never appears in TODO
- `test_todo_links_to_anchors` — each TODO row contains a markdown link (`[text](#table-N)`) pointing to the corresponding anchor in the Executive Summary

**New test class `TestComputeViolationBuckets`:**
- `test_buckets_no_violations` — empty input → all buckets empty
- `test_buckets_uncovered_no_mr` — uncovered violations without MR land in `no_mr_entries`
- `test_buckets_uncovered_with_mr` — uncovered violations with MR land in `has_mr_entries`
- `test_buckets_expiring_tiers` — expiring exceptions sorted into correct tiers based on MR coverage
- `test_buckets_counts_match_totals` — sum of all bucket counts equals total violations

**New test class `TestExtractedHelpers`:**
- `test_find_covering_mr_found` — returns matching MR
- `test_find_covering_mr_not_found` — returns None
- `test_violation_count_exact_match` — returns count from by_component_rule
- `test_violation_count_base_rule_fallback` — falls back to base rule (without `:suffix`)

**New test class `TestKeyTakeawaysRename`:**
- `test_heading_is_violations_breakdown` — `render_key_takeaways()` output starts with `## Violations Breakdown`, not `## Executive Summary`

**New test class `TestKeyTakeawaysAnchors`:**
- `test_table_anchors_present` — each table heading in render_key_takeaways output has a preceding `<a id="table-N"></a>` anchor
- `test_tooling_health_anchor` — tooling health section has `<a id="tooling-health"></a>` anchor
- `test_expiring_exceptions_anchor` — expiring exceptions bullet has `<a id="expiring-exceptions"></a>` anchor
- `test_warnings_anchor` — warnings bullet has `<a id="warnings-becoming-violations"></a>` anchor

**Updated `TestExecutiveSummaryFile`:**
- `test_todo_section_appears_first` — TODO section precedes Context Confirmation in output file
- `test_todo_section_empty_string_omitted` — empty todo string doesn't add blank section
- `test_todo_anchors_resolve` — every `#table-N` link in the TODO section has a matching `<a id="table-N"></a>` anchor in the key_takeaways section

Reuse existing test patterns: `_base_violation()` factory, `tmp_path` fixtures from conftest.py.

## Files to modify

| File | Change |
|------|--------|
| [guide_renderers.py](skills/conforma-analyze/scripts/guide_renderers.py) | Extract `_find_covering_mr`, `_violation_count` to module-level; add `_compute_violation_buckets()`, `render_todo()`; update `write_executive_summary()` |
| [generate_resolution_guide.py](skills/conforma-analyze/scripts/generate_resolution_guide.py) | Call `render_todo()`, pass to `write_executive_summary()` |
| [conforma/SKILL.md](skills/conforma/SKILL.md) | Update formatting rule about section ordering |
| [conforma/TODO.md](skills/conforma/TODO.md) | Add done item with plan/commit/Jira references |
| [test_conforma_analyze_generate_resolution_guide.py](tests/unit/test_conforma_analyze_generate_resolution_guide.py) | Add TestRenderTodo, TestComputeViolationBuckets, TestExtractedHelpers; update TestExecutiveSummaryFile |

## What this plan does NOT change

- Full resolution guide section ordering (no TODO there)
- context.yaml schema (TODO is derived from existing data at render time)
- Workflow steps in full-analysis.md (Rule 1 renders executive-summary.md verbatim — changing the file content is sufficient)
- No new CLI arguments or context.yaml keys

## Verification

1. Run existing tests: `python3 -m pytest tests/unit/test_conforma_analyze_generate_resolution_guide.py -v`
2. Run new tests specifically: `python3 -m pytest tests/unit/test_conforma_analyze_generate_resolution_guide.py -v -k "TestRenderTodo or TestComputeViolationBuckets or TestExtractedHelpers"`
3. Run conforma-analyze against a real release (e.g. `rhoai-2.19`) and verify executive-summary.md starts with TODO table
4. Verify empty categories are omitted and counts are accurate
5. Verify the full resolution guide file is unchanged (no TODO section)
6. Verify the TODO table renders correctly in GitHub markdown preview
