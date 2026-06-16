# Site Config Setup — First-Run Consent Flow

Shared reference for skills that depend on site-config values. The agent follows this flow when `site_config.py --validate` reports missing or placeholder variables.

## When to Use

Run this check at the start of any skill that needs infrastructure config (GitLab host, Konflux cluster domain, etc.). If all required variables are already set (from env vars, local config, or remote cache), this flow is skipped entirely.

## Preferred Setup: Tenant-Based Discovery

The simplest setup path requires only two values — a GitLab host and a tenant name. Everything else is auto-discovered from the `konflux-release-data` repository.

1. **Provide minimal config**:

   ```bash
   python3 scripts/site_config.py --write-local gitlab.host=YOUR_GITLAB_HOST tenant=YOUR_TENANT_NAME
   ```

2. **Verify connectivity**:

   ```bash
   python3 scripts/site_config.py --check-connectivity
   ```

   Exit codes: 0=OK, 3=DNS fail, 4=HTTPS fail, 5=auth fail, 6=project access fail.

3. **Run discovery** (optional — happens automatically on `load()`):

   ```bash
   python3 scripts/tenant_discovery.py --tenant YOUR_TENANT_NAME --human
   ```

4. **If tenant is on multiple clusters**, set `preferred_cluster`:

   ```bash
   python3 scripts/site_config.py --write-local preferred_cluster=CLUSTER_ID
   ```

After this, `site_config.load()` will automatically discover and populate:
- `KRD_CLUSTER_DOMAIN` (from tenant's cluster)
- `KRD_EC_POLICY_DIR` (EnterpriseContractPolicy directory)
- `KRD_RPA_SUBPATH` (ReleasePlanAdmission directory)
- `KRD_CLUSTER_ID`, `KONFLUX_INTERNAL_API`, `TEKTON_RESULTS_DOMAIN` (derived)

## Flow (Validation Failures)

1. **Check**: Run `python3 scripts/site_config.py --validate`.
   - Exit 0: all good, proceed.
   - Exit 1: missing required vars.
   - Exit 2: placeholder values detected (e.g. `test.example.com`, `my.cluster.p1`).

2. **Inform**: If validation fails, tell the user:

   > This skill does not have any private or internal information built in. To connect to your infrastructure (GitLab, Konflux, Slack, etc.), it needs to learn hostnames, IPs, and other locations.
   >
   > There are two ways to provide this:
   >
   > 1. **Automatic**: I can try to fetch the team's site configuration from a private GitHub repository. This requires `gh` access to that repository.
   > 2. **Manual**: You can provide the values directly and I will save them locally.
   >
   > Which would you prefer?

   If `CONFORMA_SKILL_SITE_CONFIG_URL` is set, show that URL. Otherwise, mention the default location in `red-hat-data-services/rhods-devops-infra`.

3. **Automatic path**: Run `python3 scripts/site_config.py --refresh`.
   - On success: re-run `--validate` to confirm, then proceed with the skill.
   - On failure: explain the error (usually `gh` auth or repo access), offer the manual path as fallback.

4. **Manual path**: Ask the user for the minimum required values:

   | Variable | YAML path | Description |
   |----------|-----------|-------------|
   | `GITLAB_HOST` | `gitlab.host` | Internal GitLab hostname |
   | `TENANT` | `tenant` | Konflux tenant name (enables auto-discovery) |

   Optional (only if discovery is not used):

   | Variable | YAML path | Description |
   |----------|-----------|-------------|
   | `KRD_CLUSTER_DOMAIN` | `konflux.cluster_domain` | Cluster domain (skips discovery) |
   | `PREFERRED_CLUSTER` | `preferred_cluster` | Cluster ID when tenant is on multiple clusters |
   | `GITLAB_PROJECT` | `gitlab.project` | GitLab project path (default: `releng/konflux-release-data`) |
   | `KONFLUX_NAMESPACE` | `konflux.namespace` | Konflux tenant namespace |

   Once collected, save with:

   ```bash
   python3 scripts/site_config.py --write-local gitlab.host=VALUE tenant=VALUE
   ```

5. **Verify connectivity**: Run `python3 scripts/site_config.py --check-connectivity`.

6. **Verify discovery**: Run `python3 scripts/tenant_discovery.py --tenant VALUE --human`.

## Per-Script Guards

Scripts that require specific infrastructure call `site_config.require("gitlab")` at their entry point. This is a deterministic check — it either passes silently or crashes with an actionable error. No `_setup_env.py` changes needed.

## Notes

- The agent MUST NOT silently fetch from a remote URL. Always inform and ask first.
- The `site_config.py` script is non-interactive — the consent layer is this reference, followed by the AI agent.
- Local config (`~/.config/aiops-infra/site-config.yaml`) always takes precedence over remote cache.
- Remote cache TTL is 72 hours. Run `--refresh` to force an update.
- Discovery cache TTL is 72 hours. Run `--refresh` flag to force fresh discovery.
- Placeholder values (e.g. `test.example.com`, `my.cluster.p1`) are now detected and rejected by `--validate`.
