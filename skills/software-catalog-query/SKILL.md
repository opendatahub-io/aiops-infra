---
name: software-catalog-query
description: Query the component-maturity catalog for component/image/Jira-component mappings. Resolves Konflux component names to Jira Component field values.
allowed-tools: Bash(python3:*,glab:*,git:*)
user-invocable: true
---

# Software Catalog Query

Query the RHOAI component-maturity catalog to look up component metadata: container image names, Jira Component assignments, repository mappings, and content stream tags.

The catalog data comes from `data-hub/component-maturity` on `$GITLAB_HOST`. It is maintained by the RHOAI team and updated by upstream CI.

## Prerequisites

1. **GitLab auth** to `$GITLAB_HOST` (VPN required):

```bash
glab auth status --hostname "$GITLAB_HOST"
```

If not authenticated, follow the **gitlab-auth** skill.

2. **Clone the catalog repo** (one-time, updates via `git pull`):

```bash
python3 scripts/component_catalog_ops.py ensure-repo
```

This clones `data-hub/component-maturity` to `.work/component-maturity/`. On subsequent runs it does `git pull --ff-only` to refresh data.

## Common Queries

### Resolve Konflux component names to Jira Components

Map one or more Konflux component names (with version suffixes like `-v3-5-ea-1`) to the Jira Component field value used in RHOAIENG tickets:

```bash
# Single component
python3 scripts/component_catalog_ops.py resolve --component odh-dashboard-v3-5-ea-1

# Multiple components
python3 scripts/component_catalog_ops.py resolve --components odh-dashboard-v3-5-ea-1,odh-vllm-cpu-v3-5-ea-1,rhoai-fbc-fragment-v3-5
```

Output is a JSON dict mapping each Konflux name to its Jira Component (or `null` if unmapped).

### List all component-to-Jira mappings

```bash
python3 scripts/component_catalog_ops.py list
```

Groups all mapped image names under their Jira Component.

### Run catalog queries directly

For advanced queries, run `query.py` from the cloned catalog repo:

```bash
# All RHOAI midstream artifacts with Jira component mappings
python3 .work/component-maturity/.claude/skills/software-catalog-query/scripts/query.py \
  --rh_product "Red Hat OpenShift AI" \
  --find artifacts \
  --tier midstream \
  --all-versions

# Find repos by Jira component
python3 .work/component-maturity/.claude/skills/software-catalog-query/scripts/query.py \
  --rh_product "Red Hat OpenShift AI" \
  --find repos \
  --jira_component "Serving"

# Find all Jira components
python3 .work/component-maturity/.claude/skills/software-catalog-query/scripts/query.py \
  --rh_product "Red Hat OpenShift AI" \
  --find jira_components
```

See the catalog repo's own documentation for the full `query.py` API.

## Data Refresh

The JSON reference files in the catalog repo are updated by upstream CI. To get fresh data:

```bash
cd .work/component-maturity && git pull
```

Or re-run `python3 scripts/component_catalog_ops.py ensure-repo`, which does `git pull` automatically if the repo is already cloned.

### Audit Jira Component fields on existing tickets

Scan all RHOAIENG tickets created by conforma skills and verify/fix their Jira Component field:

```bash
# Audit: show what would change
python3 scripts/component_catalog_ops.py audit-jira-components

# Fix: update Jira tickets with resolved components
python3 scripts/component_catalog_ops.py audit-jira-components --fix

# Custom JQL filter
python3 scripts/component_catalog_ops.py audit-jira-components \
  --jql 'project = RHOAIENG AND labels = "conforma-exception-ai-skill" AND component = DevOps'
```

The audit workflow:
1. Searches Jira for matching tickets
2. Extracts Konflux component / container image names from each ticket's labels (`Exception-<rule>:<component>`) and description text (`odh-*-rhel9` patterns, `quay.io/rhoai/<name>` URLs)
3. Resolves extracted names to Jira Components via the catalog
4. Outputs a JSON diff of current vs proposed components
5. With `--fix`, updates tickets that need changes (merges new components with existing ones)

## Resolution Strategy

The resolver applies four normalization strategies (first match wins):

1. **Exact match** -- the input name is in the catalog index
2. **Version-suffix stripped** -- remove `-v3-5`, `-v3-5-ea-1` etc. and retry
3. **OS-suffix stripped** -- remove `-rhel9`, `-ubi9` etc. and retry
4. **Both stripped** -- remove both suffixes and retry

The catalog index includes these additional lookup keys per entry:
- **OS-stripped variant** -- `odh-dashboard` from `odh-dashboard-rhel9`
- **`odh-` prefixed variant** -- `odh-vllm` from `vllm`
- **Repo basename** -- `vllm-gaudi` from `repos: ["red-hat-data-services/vllm-gaudi"]`
- **Underscore-normalized repo** -- `openvino-model-server` from `openvino_model_server`

Both downstream and midstream catalog tiers are loaded, with **downstream taking priority** when a name appears in both. Downstream carries exact image names (`odh-vllm-gaudi-rhel9`) with `repos` and `jira_components` data. Midstream carries bare names (`vllm`) as a fallback.

## Integration with Conforma Skills

The `component_catalog_ops.py` module is imported by `conforma-exception` scripts to auto-resolve Jira Component values when creating RHOAIENG tickets. The Jira Component field is **mandatory** for RHOAIENG tickets -- if auto-resolution fails (component not in catalog), the agent must ask the user for the correct Jira Component name.

The `reconcile_ticket()` function in `create_jira_ticket.py` uses `extract_components_from_ticket()` as a fallback when the `--components` CLI arg doesn't resolve -- it parses the ticket's own labels and description to find image names and resolve them.
