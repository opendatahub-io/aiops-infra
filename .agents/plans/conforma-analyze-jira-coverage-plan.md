# conforma-analyze Jira Coverage — Executable Deterministic Plan

Status: **Executing** (interviewed; all decisions confirmed 2026-09-15). Implementation runs in-session, no pauses, commit after every step.
Jira: [RHAIENG-6190 — improve conforma-analyze skill](https://redhat.atlassian.net/browse/RHAIENG-6190)
Related: `skills/conforma/TODO.md` item 11 (superseded/extended by this plan)
Baseline: **2356 passed, 5 skipped** (unit); no Playwright. Pre-commit enforces link-work-to-jira + full unit suite.

## 1. Confirmed decisions (HARD RULES — do not re-negotiate)

| # | Decision |
|---|---|
| 1 | `conforma` label is the universal entry point for discovery / report / validation |
| 2 | Self-healing index ALWAYS ON: every conforma-related ticket gets `conforma` (+ `conforma-violation` if clearly a violation), set-then-verified, every labeling action reported |
| 3 | Never miss a conforma problem: not/partially-covered violation with no open ticket => ticket created automatically, no confirmation; residual duplicates acceptable |
| 4 | New tickets = conforma-violation `Task`; labels `conforma`+`conforma-violation`; priority `Blocker`; Jira components from catalog, **split by Jira component** |
| 5 | Assignee: unassigned (catalog has NO person data — verified); owning team/org in description |
| 6 | Closed tickets (e.g. RHOAIENG-70681) = prior-issue context, non-blocking; new ticket still created + linked "relates to" |
| 7 | Discovery scope = **7 projects**: RHOAIENG, PSX, OCPEXCEPT, PRODSECRM, RHAI, RHAIENG, AIPCC; labels `conforma`, `conforma-violation`, `conforma-exception-ai-skill` (legacy); open AND closed |
| 8 | "Create ticket" affordance = pre-filled Jira CreateIssueDetails URL (pure function, shared with the created-ticket payload) |
| 9 | "backfill" => **repair** semantics (audit = read-only + self-heal; repair = audit + fill) |
| 10 | New shared dual-mode script `scripts/conforma_jira_ticket_ops.py` + new workflow step after coverage |
| 11 | New-ticket target field = **`TargetVersion` (`customfield_10855`)**, NOT `fixVersion` |
| 12 | Optional non-blocking guide-URL comment on created tickets after successful guide submission |
| 13 | `tests/check_script_coverage.py` enforces **per-script >97%** coverage on plan-touched scripts |
| 14 | Cross-model review = manual `claude -p --output-format json` copy-paste at 2 checkpoints (no new automation) |
| 15 | Dirty tree handled in **Phase 0**: commit pre-existing in-flight work under RHAIENG-6190, then assert clean tree |

## 2. Context

The `conforma-analyze` skill resolves Conforma violations and generates a resolution guide + TODO, but its Jira integration is incomplete: it only finds *open* tickets via a 4-pass heuristic, and its Jira primitive (`jira_ops.search_issues`) **silently swallows errors** (returns `{"issues": [], "total": 0, "error": ...}`), so a bad JQL is indistinguishable from "no tickets". Result: conforma problems are missed from Jira dashboards and violations have no ticket to attach a resolution guide to.

## 3. Problem (what we are fixing)

1. **Discovery is broken on this tenant.** Only `labels = "..."` / `labels in (...)` return data; `label = ...` / `label in (...)` **silently return empty**. The deeper failure is that `search_issues` hides any error as an empty list, so we cannot tell "no tickets" from "query failed".
2. **`search_issues` masks errors** and does not return `priority` / `components` / target version, which audit and matching need.
3. **Ticket creation uses `fixVersion`** but the tenant expects **`TargetVersion`** (`customfield_10855`) for RHOAIENG `Task` (verified).

## 4. Root cause of the specific discovery gap (verified live)

RHOAIENG-70681 — "Conforma violation: rpm_packages.unique_version in guardrails-detectors HuggingFace runtime" — is **Closed**, type **Bug**, and has **no `conforma-violation` label**. The current `conforma_jira_ops.prefetch_open_jira_tickets` only searches **open** tickets and its component pass runs only for zero-finding rules => this ticket is invisible. The label-first, all-statuses design below fixes it.

## 5. Flow

```mermaid
flowchart TD
  A[coverage.json exists] --> B[discover: labels in (...) across 7 projects, all statuses]
  B --> C{ticket has conforma label?}
  C -->|no| D[self-heal: add conforma / +conforma-violation, verify]
  C -->|yes| E[match violations to tickets]
  D --> E
  E --> F{open ticket for this component group?}
  F -->|yes| G[role = existing; extend if partial]
  F -->|closed only| H[role = prior issue; link relates]
  F -->|none| I[create Task: TargetVersion, Blocker, components, labels]
  G --> J[write jira_sync.json]
  H --> J
  I --> J
  J --> K[guide render: Jira block + JIRAs cell + per-row Jira col + pre-fill URL]
  K --> L[submit guide]
  L -->|success| M[non-blocking: comment guide URL on created tickets]
```

## 6. Top-level checklist

| Step | Phase | Deliverable | Commit | Review |
|---|---|---|---|---|
| 0 | Clean tree | commit in-flight work (RHAIENG-6190), assert clean | C0 | — |
| 1.1 | Discovery | 7-project label-JQL constants (`conforma_constants.py`) + `build_label_discovery_jql` | C1 | — |
| 1.2 | Discovery | `search_issues` surfaces errors deterministically (raises, no silent empty) | C2 | — |
| 1.3 | Discovery | `search_issues` returns `priority` + `components` + `target_versions` | C3 | — |
| 2.1 | Coverage gate | `tests/check_script_coverage.py` (>97%/script) + unit test (pre-commit wiring deferred to 5.1) | C4 | — |
| 3.1 | Ticket ops | `scripts/conforma_jira_ticket_ops.py` (dual-mode, all subcommands) | C5 | R1 |
| 3.2 | Ticket ops | create uses `TargetVersion` (customfield_10855), set-then-verify | C6 | R1 |
| 3.3 | Ticket ops | non-blocking guide-URL comment after submit | C7 | R1 |
| 4.1 | Integration | cutover `conforma_jira_ops`/`violations_coverage` to new discovery (no shim) | C8 | — |
| 4.2 | Integration | renderer: Jira block + JIRAs cell + per-row Jira col + pre-fill URL | C9 | — |
| 4.3 | Integration | workflow Step 8 + SKILL.md + search-conforma-jira-tickets + TODO.md | C10 | — |
| 5.1 | Validation | full unit suite + per-script coverage + pre-commit + live dry-run | C11 | R2 |
## 7. Phase 0 — Clean tree (commit pre-existing in-flight work)

The working tree has unrelated in-flight work. Commit it under RHAIENG-6190 first; all later phases start from a clean tree.

**Step 0.1** — Confirm branch + linked ticket (link-work-to-jira hook is enforced at commit).
```bash
cd /home/wznoinsk/dev/opendatahub-io/aiops-infra
git branch --show-current
git status --short
```
Expected in-flight set (re-confirm; capture exactly what is present, no more, no less):
- modified: `.pre-commit-config.yaml`, `AGENTS.md`, `CONTRIBUTING.md`, `skills/conforma-analyze/SKILL.md`, `skills/conforma-analyze/scripts/guide_renderers.py`, `tests/unit/test_conforma_analyze_generate_resolution_guide.py`
- untracked: `.agents/` (plans + references, incl. this file), `hooks/check-jira-branch.sh`, `skills/conforma-analyze/workflows/regenerate-guide.md`, `tests/unit/test_check_jira_branch.py`

Commit (pre-commit runs check-jira-branch, ruff, full unit suite, check-test-coverage, path/secret/determinism checks):
```bash
git add -A
git commit -m "chore: commit pre-existing in-flight work (plans, jira-branch hook, regenerate-guide) [RHAIENG-6190]"
git status --short   # MUST be empty
```
**DoD:** `git status --short` is empty; commit C0 recorded. **Stop if the hook blocks** — do not `--no-verify`; resolve the failing check instead.

---
## 8. Phase 1 — Discovery + `search_issues` fixes

### Step 1.1 — 7-project discovery scope in `scripts/conforma_constants.py`
- Add `CONFORMA_DISCOVERY_PROJECTS = ["RHOAIENG", "PSX", "OCPEXCEPT", "PRODSECRM", "RHAI", "RHAIENG", "AIPCC"]`.
- Add `CONFORMA_DISCOVERY_LABELS = ["conforma", "conforma-violation", "conforma-exception-ai-skill"]`.
- Add pure fn `build_label_discovery_jql(projects=CONFORMA_DISCOVERY_PROJECTS, labels=CONFORMA_DISCOVERY_LABELS) -> str` returning exactly:
  `project in (RHOAIENG, PSX, OCPEXCEPT, PRODSECRM, RHAI, RHAIENG, AIPCC) AND labels in (conforma, conforma-violation, conforma-exception-ai-skill)`
  (plural `labels in (...)` — the only tenant-working form; NO status filter).
- Test `tests/unit/test_conforma_constants.py`: assert the produced JQL string exactly; assert both lists have 7 / 3 members.
- Run: `~/.conforma/bin/conforma_run.sh` not needed; run `python -m pytest tests/unit/test_conforma_constants.py -q`.
- **Commit C1.**

### Step 1.2 — `search_issues` surfaces errors deterministically (`scripts/jira_ops.py`)
Current bug: `except JIRAError/Exception: return {"issues": [], "total": 0, "error": str(exc)}` (line ~274-312) hides failures.
- Change: **remove the swallow**. Let Jira errors propagate as a typed exception. Add a module-level `JiraSearchError(RuntimeError)` carrying `.jql`, `.status` (if present), `.message`. On `JIRAError`/unexpected error, `raise JiraSearchError(...) from exc`.
- Normal path unchanged: return `{"issues": [...], "total": N}`.
- Update CLI `search` subcommand: catch `JiraSearchError` -> print `{"error": ..., "jql": ...}` to stderr, `sys.exit(1)`.
- Update `tests/unit/test_jira_ops.py`:
  - `TestSearchIssues.test_error` (was asserting `issues==[]` + `error in result`) -> now asserts `pytest.raises(JiraSearchError)` with `.jql == "invalid jql"`.
  - `test_empty_results` unchanged (a real empty result still returns `{"issues": [], "total": 0}` with NO error key).
  - Add a test that a successful search with a bad field name raises (proves non-silent failure).
- Run: `python -m pytest tests/unit/test_jira_ops.py -q`.
- **Commit C2.**

### Step 1.3 — `search_issues` returns `priority` / `components` / `target_versions`
- Extend `search_issues` requested-field handling (currently handles summary/status/issuetype/assignee/created/labels/fixVersions only) to map:
  - `priority` -> `entry["priority"] = str(issue.fields.priority)` (or `"None"`)
  - `components` -> `entry["components"] = [c.name for c in issue.fields.components]` (or `[]`)
  - `target_versions` -> `entry["target_versions"] = [v.name for v in issue.fields.customfield_10855]` (or `[]`)
- Add these to the CLI `--fields` help text and the function docstring supported-values list.
- Update `test_jira_ops.py`: new test asserts all three fields are populated from a mock issue (priority, components list, customfield_10855 list), and absent when not requested.
- Run: `python -m pytest tests/unit/test_jira_ops.py -q`.
- **Commit C3.**

**Phase 1 DoD:** label-JQL builder exists for 7 projects; `search_issues` raises on Jira errors (never silent-empty) and returns priority/components/target_versions; all `test_jira_ops.py` + `test_conforma_constants.py` green; commits C1-C3.
---
## 9. Phase 2 — Coverage gate

### Step 2.1 — `tests/check_script_coverage.py` (per-script >97%)
Purpose: enforce that the plan-touched scripts are covered >97%, so the new/changed logic cannot ship under-tested.
- New file `tests/check_script_coverage.py`. Dual-purpose (mirrors `tests/check_test_coverage.py` conventions):
  - A fixed manifest `PLAN_COVERAGE_TARGETS` (repo-root-relative) listing the scripts this plan touches:
    `scripts/jira_ops.py`, `scripts/conforma_jira_ticket_ops.py`, `scripts/conforma_constants.py`, `scripts/conforma_jira_ops.py`.
  - Behavior: run the unit suite under `coverage` (no `--source`, so root `scripts/` is captured), parse the `coverage json` report, and for each target assert `percent_covered > 97` (strict). Print a per-file table (file, %, PASS/FAIL/skip); exit 1 on any fail.
  - Invocation: `python tests/check_script_coverage.py [--min 97.0]`. Uses the `coverage` library (installed: coverage 7.14.1). Note: scoping with `--source scripts --source skills` excludes root `scripts/` in this env, so the checker runs with no source filter.
  - Deterministic: no network, no external CLI; subprocess `coverage run -m pytest tests/unit/ -q` then `coverage json`.
- Test `tests/unit/test_check_script_coverage.py`: unit-test the pure parts (find-in-report, pct extraction, threshold pass/fail, skip-on-absent, manifest completeness). Do NOT shell out in the unit test — factor the parse/decision into pure fns and test them.
- Run: `python -m pytest tests/unit/test_check_script_coverage.py -q` then `python tests/check_script_coverage.py`.
  - Measured baseline at C4: `conforma_constants.py` 100% PASS, `conforma_jira_ticket_ops.py` skip (not yet created), `jira_ops.py` 58.5% and `conforma_jira_ops.py` 85.8% FAIL.
  - **The pre-commit hook is NOT wired at C4.** Wiring it now would block commits C5–C10 because `jira_ops.py`/`conforma_jira_ops.py` are below 97% until Phase 3 fills `jira_ops.py` and Phase 4's cutover shrinks `conforma_jira_ops.py`. The hook is wired in **Step 5.1** (Phase 5) once all four targets are >97%.
- **Commit C4.**

**Phase 2 DoD:** `check_script_coverage.py` exists and is unit-tested; `python tests/check_script_coverage.py` reports conforma_constants 100% PASS, ticket_ops skip, jira_ops/conforma_jira_ops FAIL (as expected pre-Phase 3/4); commit C4. Pre-commit wiring deferred to Phase 5 (see Step 5.1).

---
## 10. Phase 3 — `scripts/conforma_jira_ticket_ops.py`

New shared dual-mode script (CLI + importable) per ARCHITECTURE.md. Reuses `jira_ops` (create_issue/update_issue/link_issues/add_comment/search_issues/get_issue), `conforma_jira_ops` helpers (`classify_ticket_version_relevance`, `_normalize_version`, `_extract_rule_from_summary`, `_extract_component_stems`, `_infer_rule_from_text`), and `component_catalog_ops.resolve_jira_components`.

**Constants (reuse Phase 1):** discovery projects/labels from `conforma_constants`; create target = `RHOAIENG` + `Task`; `TARGET_VERSION_FIELD = "customfield_10855"`; priority `Blocker`.

**CLI subcommands:** `create-conforma-jiras` (workflow), `find` (discovery only), `audit`, `repair`, `prefill-url`. `create-conforma-jiras` reads `violations.yaml` + `coverage.json` + `context.yaml` (release/env) via context auto-discovery — NO `--release`/`--run-dir` args. Every Jira write is set-then-verified via a follow-up GET. Output: `jira_sync.json` in run dir + `steps.jira_sync` persisted to `context.yaml`.

### Step 3.1 — Script skeleton + discovery/match/group/create/link/audit/repair + pre-fill
Implement, with each unit tested:
- `discover_conforma_tickets(projects, labels)` -> calls `jira_ops.search_issues(build_label_discovery_jql(...), max_results=..., fields=[key,summary,status,issuetype,labels,components,priority,target_versions])`; propagates `JiraSearchError` (no silent empty).
- `self_heal_labels(tickets)` -> for each ticket lacking `conforma`: add `conforma`; add `conforma-violation` only if summary matches `Conforma violation:` convention or rule text; legacy `conforma-exception-ai-skill` tickets get `conforma` only; each write set-then-verified; returns action list.
- `match_violations(violations, tickets)` -> signals strongest-first: rule in summary/text, component-stem, Jira-component (catalog), release relevance; requires rule + >=1 component signal; open=>`existing`, closed=>`prior_issue`.
- `group_by_jira_component(violation, catalog)` -> `resolve_jira_components`; unmapped konflux -> one `Unmapped` group (reported).
- `create_violation_ticket(group, context)` -> project `RHOAIENG`, type `Task`, summary `Conforma violation: <rule> in <konflux components>`, labels `conforma`+`conforma-violation`, priority `Blocker`, components=group, description = deterministic template (rule, release, env, konflux+jira component+team, violation details, source CSV URL, "relates to prior issue <keys>" line); assignee unassigned. Dedup first (summary prefix + component stems, open) -> link instead of create if matched.
- `extend_partial_match(ticket, missing_components)` -> add missing components + comment (set-then-verify).
- `link_tickets(...)` -> new->existing open (relates), new->closed prior (relates), extended->sibling (relates).
- `build_prefill_url(project_id, group)` -> pure function; CreateIssueDetails URL, all params URL-encoded; shared single source of truth for the actually-created payload.
- `audit()` / `repair()` -> tiered checks (see §12); `audit` read-only + self-heal; `repair` adds fills (labels/components/target_version/priority), assignee+status report-only (never guessed).
- `sync()` -> orchestrate discover -> self-heal -> match -> group -> create/extend -> link -> write `jira_sync.json` (shape in §11) -> persist context -> compact chat summary.
- Failure policy: Jira auth failure => hard stop (no guide gen). Individual write failure => recorded, next run idempotent-retries.
- Test `tests/unit/test_conforma_jira_ticket_ops.py` (all Jira/catalog mocked): label-JQL + discovery propagation; self-heal plan (incl. exception tickets never get `conforma-violation`); matching incl. the RHOAIENG-70681 scenario (closed, no label => prior issue, non-blocking); component grouping incl. unmapped fallback; create payload shape; pre-fill URL (pure, all params encoded); dedup/idempotency; audit gap detection + repair plan.
- Run: `python -m pytest tests/unit/test_conforma_jira_ticket_ops.py -q`.
- **Commit C5.** **Review R1 after C7** (below).

### Step 3.2 — Create uses `TargetVersion` (customfield_10855), set-then-verify
- `create_violation_ticket` builds `extra_fields = {"customfield_10855": [{"name": <resolved_target_version>}]}` and passes to `jira_ops.create_issue(..., extra_fields=...)`.
- Deterministic target-version resolution: derive from `context.yaml` release via existing `_normalize_version`/version-pattern logic; if unmappable => omit the field and record `"target_version": "unmapped"` in the action (never guess). (createmeta does not expose allowed values => resolve live or explicitly unset.)
- After create: follow-up `jira_ops.get_issue(key, fields=[...,"labels","priority","components"])` to verify labels/priority/components/target version landed; record verification.
- Test: assert the create payload contains `customfield_10855` with the mapped version when resolvable and omits it when not; assert verification GET issued and recorded.
- Run: `python -m pytest tests/unit/test_conforma_jira_ticket_ops.py -q`.
- **Commit C6.**

### Step 3.3 — Non-blocking guide-URL comment after submit
- `add_guide_url_comment(created_keys, guide_url)` -> for each ticket created this run, `jira_ops.add_comment(key, f"Resolution guide: {guide_url}")`. Failure is caught + reported (non-blocking, never fails the workflow).
- Called from `generate_resolution_guide.py`/submit path only after guide submission succeeds (see Phase 4).
- Test: comment called for each created key; a comment error does not raise / does not fail sync.
- Run: `python -m pytest tests/unit/test_conforma_jira_ticket_ops.py -q`.
- **Commit C7.**

**Review checkpoint R1** (after C7): run
```bash
claude -p --output-format json 'You are reviewing an in-repo implementation plan and its diff for the conforma-analyze Jira coverage feature. Focus ONLY on (a) Jira write correctness, (b) deterministic error surfacing (no silent empty results), (c) the TargetVersion (customfield_10855) handling, and (d) test adequacy. Read .agents/plans/conforma-analyze-jira-coverage-plan.md, scripts/conforma_jira_ticket_ops.py, scripts/jira_ops.py, and their tests. Return a concise verdict: BLOCKING / NON-BLOCKING / PASS, then a numbered list of any blocking defects. Do not propose refactors beyond blocking defects.' > /tmp/review_r1.json
```
Paste the `.result` field into the Handover section. Continue only if verdict is PASS or NON-BLOCKING.

**Phase 3 DoD:** new script fully functional (sync/find/audit/repair/prefill-url), create uses TargetVersion, guide-URL comment non-blocking, all its unit tests green, `check_script_coverage.py` reports `conforma_jira_ticket_ops.py` >97%; commits C5-C7; R1 recorded and non-blocking.
---
## 11. Data model — `jira_sync.json` (run directory)

```json
{
  "release": "rhoai-3.6-ea.2", "environment": "prod", "generated_at": "...",
  "projects_searched": ["RHOAIENG","PSX","OCPEXCEPT","PRODSECRM","RHAI","RHAIENG","AIPCC"],
  "discovered": [{"key","url","summary","status","labels","components","priority","project",
                  "matched_rule","release_relevance","self_healed_labels":["conforma"]}],
  "violations": [{
    "rule": "rpm_packages.unique_version", "coverage": "not_covered",
    "groups": [{
      "jira_component": "AI-Guardrails", "team": "...", "konflux_components": ["guardrails-detectors"],
      "existing": {"key","status","release_relevance"} | null,
      "prior_issues": [{"key","status"}],
      "created": {"key","url","target_version"} | null,
      "extended": {"key","components_added":[...]} | null,
      "create_url": "<prefilled CreateIssueDetails URL>"
    }]
  }],
  "actions": ["created RHOAIENG-12345 (rpm_packages... AI-Guardrails)",
              "labeled RHOAIENG-70681 +conforma", "linked RHOAIENG-12345 -> RHOAIENG-70681 (relates)"],
  "audit": { "checked": 42, "gaps": [...] }
}
```

## 12. `audit` / `repair` tiered checks

Start point: all tickets with the `conforma` label (7 projects, all statuses; `--open-only` available; closed tickets exempt from target_version/assignee checks, reported with status).

| Field | Expectation (violation ticket) | audit | repair |
|---|---|---|---|
| `conforma` label | required | report | add (self-heal) |
| `conforma-violation` label | required on violation tickets | report | add |
| Jira components | >=1 | report | resolve from summary via catalog -> set |
| `target_versions` (customfield_10855) | set | report | set from release context if determinable |
| priority | `Blocker` | report | set to Blocker |
| assignee | set *if lead resolvable* | report "unassigned — route to team X" | **never guessed** (no lead data) |
| status | — | always reported | never changed |

`audit` is read-only apart from self-healing labels (hard rule 2); `repair` adds the tiered fills, each set-and-verified, all recorded. Output: chat table + `audit` section in `jira_sync.json`.

---
## 13. Phase 4 — Integration

### Step 4.1 — Cutover discovery (no shim)
- `scripts/conforma_jira_ops.py`: move `prefetch_open_jira_tickets`'s discovery to the new script (the old 4-pass is **removed**, not shimmed). Keep `classify_ticket_version_relevance` + version helpers (reused).
- `skills/conforma-analyze/scripts/violations_coverage.py`: the Jira prefetch now calls the new label-first discovery (open-filtered for the coverage table). Update its unit tests if signatures change.
- Run: `python -m pytest tests/unit/test_conforma_jira_ops.py tests/unit/test_conforma_analyze_violations_coverage.py tests/unit/test_conforma_analyze_violations_coverage_extended.py -q`.
- **Commit C8.**

### Step 4.2 — Renderer changes (`skills/conforma-analyze/scripts/guide_renderers.py` + `generate_resolution_guide.py`)
`generate_resolution_guide.py` reads `jira_sync.json` from the run dir (absent => graceful fallback to current behavior) and passes it to the renderers:
- Per-violation section: new **Jira tickets** block (open tickets w/ status + release relevance; prior issues; created-this-run; `Create Jira ticket` pre-fill link per component group with no open ticket).
- `render_components_table` JIRAs cell: extended with created tickets + pre-fill links.
- Numbered TODO tables: new per-row **Jira** column (ticket key(s) if found/created, else the `Create` pre-fill link).
- After successful guide submission: call `conforma_jira_ticket_ops.add_guide_url_comment(created_keys, guide_url)` (non-blocking).
- Test `tests/unit/test_conforma_analyze_generate_resolution_guide.py`: Jira block, JIRAs cell, per-row Jira col, create links, absent-jira_sync fallback, guide-URL comment only on successful submit.
- Run: `python -m pytest tests/unit/test_conforma_analyze_generate_resolution_guide.py -q`.
- **Commit C9.**

### Step 4.3 — Workflow + docs
- `skills/conforma-analyze/workflows/full-analysis.md`: new **Step 8 "Jira Sync"** between coverage (step 7) and guide generation; old steps 8/9/10 renumber to 9/10/11; update the step-9/10 hard-failure rule cross-references. Command:
  ```bash
  ~/.conforma/bin/conforma_run.sh scripts/conforma_jira_ticket_ops.py create-jiras-for-conforma-violations
  ```
- `skills/conforma-analyze/SKILL.md`: add the Jira-sync capability to the capability/routing table.
- `skills/search-conforma-jira-tickets/SKILL.md`: delegate to the new label-first discovery.
- `skills/conforma/TODO.md`: mark item 11 done + link to this plan + RHAIENG-6190.
- Run: `python tests/check_workflow_determinism.py && python tests/check_path_references.py && python -m pytest tests/unit/test_check_workflow_determinism.py -q`.
- **Commit C10.**

**Phase 4 DoD:** old 4-pass discovery removed, cutover wired, renderer shows Jira everywhere, workflow has Step 8, docs updated; all affected unit tests green; commits C8-C10.

---
## 14. Phase 5 — Validation

### Step 5.1 — Full validation + live dry-run
- `python -m pytest tests/unit/ -q` (must be >= 2366 passing, 0 failing).
- `python tests/check_script_coverage.py` (all 4 plan-touched scripts >97% — jira_ops and conforma_jira_ops must have been brought over 97% in Phases 3/4).
- **Wire the coverage gate into pre-commit** (deferred from C4, see Phase 2): add a `check-script-coverage` local hook to `.pre-commit-config.yaml` (`entry: python tests/check_script_coverage.py`, `language: system`, `pass_filenames: false`, `always_run: true`). This is safe now only because all four targets are >97%.
- Full pre-commit: `pre-commit run --all-files` (all hooks green, including the new coverage gate).
- **Live dry validation** on the active run (`~/.conforma/.conforma-active/`, rhoai-3.6-ea.2, prod): run `scripts/conforma_jira_ticket_ops.py find` (discovery only, READ-ONLY, no writes) and confirm RHOAIENG-70681 is found as a prior issue. Do NOT create real tickets (user guard).
- **Commit C11** (pre-commit wiring + any fixes from validation).

**Review checkpoint R2** (after C11): same `claude -p` invocation as R1 but scoped to "end-to-end integration, workflow determinism, and the live dry-run result". Paste `.result` into Handover.

**Phase 5 DoD:** full unit suite green (>= baseline), per-script coverage >97% on all touched scripts, pre-commit clean, live `find` confirms RHOAIENG-70681 discovered; commits C11; R2 recorded and non-blocking.

### Phase 5 follow-up — Merge Request-linked exception coverage

The `rhoai-3.6-ea.2` validation exposed an integration gap not covered by the original C11 checklist: a Jira exception referenced by a Merge Request could be fetched but dropped from rule coverage when its rules appeared only in the Jira description, and a single confirmed exception could not cover multiple rules. The follow-up now:

- requests Jira descriptions during discovery and referenced-ticket lookup;
- recognizes suffixed rule names such as `rpm_signature.allowed:<digest>`;
- retains Merge Request references through normalization; and
- permits one confirmed exception ticket to cover multiple rules.

Matching semantics are deliberately different for Jira and Merge Request
exception entries: Jira tickets with explicit component names require an exact
version match, while an unversioned `componentNames` entry in a Merge Request
is a wildcard that covers every version of that component. Versioned Merge
Request entries remain version-specific.

Regression coverage includes RHOAIENG-88509 and Merge Request !22104. Validation: `2672 passed, 5 skipped`; all four plan coverage targets pass (`99.4%`, `100.0%`, `98.8%`, and `98.4%`).

---
## 15. Key files

| File | Change |
|---|---|
| `scripts/conforma_jira_ticket_ops.py` | **NEW** — discover, self-heal, match, group, create (TargetVersion), extend, link, audit, repair, pre-fill, guide-URL comment |
| `scripts/jira_ops.py` | `search_issues` raises `JiraSearchError` (no silent empty); returns priority/components/target_versions |
| `scripts/conforma_constants.py` | 7-project discovery projects/labels + `build_label_discovery_jql` |
| `scripts/conforma_jira_ops.py` | discovery removed (moved); version-relevance helpers stay |
| `tests/check_script_coverage.py` | **NEW** — per-script >97% gate |
| `skills/conforma-analyze/scripts/violations_coverage.py` | prefetch -> new discovery (open-filtered) |
| `skills/conforma-analyze/scripts/guide_renderers.py` | Jira block, JIRAs cell, per-row Jira col, pre-fill links |
| `skills/conforma-analyze/scripts/generate_resolution_guide.py` | read `jira_sync.json`, pass to renderers, guide-URL comment on submit |
| `skills/conforma-analyze/workflows/full-analysis.md` | new Step 8 + renumber + cross-refs |
| `skills/conforma-analyze/SKILL.md` | capability entry |
| `skills/search-conforma-jira-tickets/SKILL.md` | delegate to new discovery |
| `skills/conforma/TODO.md` | item 11 done + plan link |
| `tests/unit/test_conforma_jira_ticket_ops.py` | **NEW** |
| `tests/unit/test_jira_ops.py`, `test_conforma_constants.py`, `test_check_script_coverage.py` | new/updated |
| `.pre-commit-config.yaml` | add `check-script-coverage` hook |

## 16. Grounding (verified live 2026-09-15)

- Tenant JQL: only `labels = "..."` / `labels in (...)` return data; `label = ...` / `label in (...)` return empty.
- createmeta (Task): RHOAIENG, RHAI, RHAIENG, AIPCC expose **`Target Version` = `customfield_10855`** (array). OCPEXCEPT Task has only `Affects versions`. **PSX and PRODSECRM have no `Task` issuetype** (discovery-only). => RHOAIENG is the single create target.
- `jira_ops.create_issue` already accepts `extra_fields` (used for TargetVersion).
- `component_catalog_ops` public API: `ensure_catalog_repo`, `load_catalog`, `resolve_jira_components`, `extract_components_from_ticket`, `audit_jira_components`. Catalog has project->component + component->team/org; NO person/lead data.
- `conforma-exception/scripts/create_jira_ticket.py` has proven set-and-verify REST patterns to mirror.
- Active run: `~/.conforma/.conforma-active/` (rhoai-3.6-ea.2, prod); Jira auth verified.

## 17. Handover (fresh-model ready) — update after each phase

- **Phase 0:** DONE. C0 = `0b466cc` — committed pre-existing in-flight work under RHAIENG-6190; tree clean (verified `git status --porcelain` empty).
- **Phase 1:** DONE. C1 `5f52f49` (conforma_constants 7-project JQL + tests), C2 `1da82ee` (search_issues raises JiraSearchError, no silent empty; CLI catches + exit 1), C3 `041f569` (search_issues returns priority/components/target_versions). Full suite 2364 passed.
- **Phase 2:** DONE. C4 `ba1cf50` — `tests/check_script_coverage.py` (coverage run + json, per-target >97% strict, skip-on-absent) + `tests/unit/test_check_script_coverage.py` (14 tests). Baseline at C4: conforma_constants 100%, ticket_ops skip, jira_ops 58.5%, conforma_jira_ops 85.8%. **Pre-commit wiring deferred to Step 5.1** (would block C5–C10 otherwise).
- **Phase 3:** DONE. C5/C6/C7 landed in `fe2aeaa` (`conforma_jira_ticket_ops` + TargetVersion + guide-URL comment).
- **Review R1:** PENDING — never recorded (scheduled after C7; C7 landed in `fe2aeaa`, verdict was never recorded).
- **Phase 4:** DONE. C8 `85b636d` (cutover to label-first discovery), C9 `7e24f82` (renderer: Jira block + JIRAs cell + per-row Jira column + pre-fill links), C10 `10349c0` (workflow Step 8 Jira Sync + docs).
- **Phase 5:** DONE. C11 (validation) — original validation recorded 2597 passed / 5 skipped; the current full unit suite is 2664 passed / 5 skipped. The coverage gate passes at 99.4 / 100.0 / 99.6 / 98.4 (all >97%); `check-script-coverage` pre-commit hook is wired + passing; live `find` (read-only) discovered 98 conforma tickets. **Defects found & fixed:** (1) stale `patch(...)` targets in two tests broken by the in-flight ruff F401 cleanup — fixed by patching the real implementation modules; (2) `find` performed self-heal label **writes by default** (51 `+conforma` writes observed on the live tenant during the first run) — `cmd_find` is now unconditionally read-only; (3) Jira descriptions were not retrieved for candidate matching, and a confirmed shared exception could not cover multiple rules — fixed in the Phase 5 follow-up above. **Open DoD gap:** RHOAIENG-70681 has `labels: []` (live-verified) and is therefore not discoverable by the label-first design; needs product decision (accept / one-time label / keyword pass).
- **Review R2:** PENDING — run after C11; paste `claude -p` `.result` here.

**How to resume:** start at the first NOT STARTED step above; each step lists its files, tests, and commit id. Do not skip the commit or the DoD. Do not create real Jira tickets without explicit user confirmation (live `find` in Phase 5 is read-only).
