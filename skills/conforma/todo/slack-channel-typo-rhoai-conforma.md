# Slack channel typo — the channel is `#rhoai-conforma`, not `#conforma`

Status: **NOT STARTED**
Origin: `rhoai-3.6-ea.1` Conforma report run (`~/.conforma/20260921T104043Z/`) — during the post-submission Slack step the question text referenced `#conforma`. The user confirmed the correct Conforma Slack channel is **`#rhoai-conforma`**.

## Goal

Ensure no script, skill, workflow, or other repository file refers to the Conforma Slack channel as `#conforma`. The canonical channel name is `#rhoai-conforma`. The channel name must have exactly one source of truth so that neither scripts nor the agent invent it.

## Current findings (repo scan, 2026-09-21)

- The only literal `#conforma` in the repository is in a test fixture:
  - `tests/unit/test_conforma_analyze_generate_resolution_guide.py:1682` feeds `{"channel": "conforma", ...}` to `render_components_table(...)`.
  - `tests/unit/test_conforma_analyze_generate_resolution_guide.py:1695` asserts the rendered row contains `[#conforma](https://slack/t1)`.
- The renderer is **not** at fault: `skills/conforma-analyze/scripts/guide_renderers.py` (Slack thread label) and `skills/conforma-analyze/scripts/violations_coverage.py` both print `[#{channel}]` from the channel name supplied by the Slack search data, so the rendered output is correct whenever the underlying data is.
- The wrong `#conforma` in the `rhoai-3.6-ea.1` run came from the **agent-composed Slack post question**, not from a script — no canonical channel constant exists to anchor on (checked `scripts/conforma_constants.py`, `scripts/conforma_slack_ops.py`, and the `conforma-analyze` workflow; none defines the channel name).
- Unrelated channel references that must NOT be touched:
  - `skills/conforma-remedy/SKILL.md` — `#konflux-users` (escalation channel for unrecognized violations).
  - `skills/references/violation-catalog.yaml` — `#rhoai-konflux-poc-notifications` (symptom of the `no_conforma_report_in_slack` operational issue).
  - `skills/search-conforma-slack-threads/SKILL.md` — `konflux-users` in an example output.

## Scope

1. Establish `#rhoai-conforma` as the single source of truth for the Conforma Slack channel name (constant in `scripts/conforma_constants.py` or the product configuration used by the conforma skills — keep the script product-agnostic per convention; do not hardcode product values inline).
2. Verify `#rhoai-conforma` is the channel where Conforma reports/notifications actually land (cross-check the `conforma-reporter` GitHub Action notification step or `~/.conforma/.env`) before encoding it.
3. Fix every user-facing occurrence of the bare `#conforma` spelling that actually means the Conforma channel. Test fixtures that deliberately exercise the renderer with an arbitrary channel name may keep a neutral fake value, but must not read as the canonical channel name.
4. Anchor the `conforma-analyze` workflow's Slack post step on the constant (or state the channel name explicitly there) so the agent-generated question text cannot drift.
5. Add a unit test for the new constant and a grep-based regression check that no non-canonical `#conforma`-only spelling is committed.

## DoD

- `grep -rnF '#conforma' <repo>` (excluding `.git/`, `__pycache__/`, and generated caches) returns only `#rhoai-conforma` occurrences (or documented fixture exceptions).
- The channel constant exists with a unit test, and the workflow references it.
- A fresh `conforma-analyze` run asks to post the report to `#rhoai-conforma`.

## Verification command

```bash
grep -rnF -- '#conforma' . \
  --include='*.py' --include='*.md' --include='*.yaml' --include='*.yml' --include='*.sh' --include='*.json' \
  | grep -vF '#rhoai-conforma' \
  | grep -v '/.git/' | grep -v __pycache__
```

Must print nothing (or only explicitly documented exceptions).
