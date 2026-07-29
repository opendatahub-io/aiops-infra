# Infrastructure Setup — First-Run Flow

Shared reference for skills that need infrastructure config (GitLab host, Konflux cluster domain, etc.). The agent follows this flow when `verify_conforma_prerequisites.py` reports missing infrastructure variables.

## When to Use

Run the prerequisites check (`_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/verify_conforma_prerequisites.py" --fix`) at the start of any skill that needs infrastructure config. If all required variables are already set (from `~/.conforma/.env` or discovery cache), this flow is skipped entirely.

## Setup: Add to ~/.conforma/.env

The setup requires only two values. Everything else is auto-discovered from the `konflux-release-data` repository via the GitLab Tree API.

1. **Add to `~/.conforma/.env`**:

   ```
   GITLAB_HOST=your-gitlab-host
   TENANT=your-tenant-name
   ```

2. **Verify discovery** (optional — happens automatically on load):

   ```bash
   ~/.conforma/bin/conforma_run.sh scripts/konflux_tenant_env_discovery.py --tenant YOUR_TENANT_NAME --human
   ```

3. **If tenant is on multiple clusters**, add `PREFERRED_KONFLUX_CLUSTER` to `~/.conforma/.env`:

   ```
   PREFERRED_KONFLUX_CLUSTER=cluster-id
   ```

After this, auto-discovery will populate:
- `KONFLUX_CLUSTER_DOMAIN` (from tenant's cluster)
- `KONFLUX_CONFORMA_POLICY_DIR` (Conforma policy directory)
- `KONFLUX_RPA_SUBPATH` (ReleasePlanAdmission directory)
- `KONFLUX_CLUSTER_ID`, `KONFLUX_INTERNAL_API`, `TEKTON_RESULTS_API_DOMAIN` (derived)

## If Discovery Fails

If auto-discovery cannot work in your environment (no VPN, tenant not registered, custom setup), add the required variables directly to `~/.conforma/.env`:

```
KONFLUX_CLUSTER_DOMAIN=your-cluster-domain
```

To debug discovery failures:

```bash
~/.conforma/bin/conforma_run.sh scripts/konflux_tenant_env_discovery.py --tenant $TENANT --human
```

## Flow (Agent Behavior on Validation Failures)

1. **Check**: Run `_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/verify_conforma_prerequisites.py" --fix`. Present output verbatim.
   - Exit 0: all good, proceed.
   - Exit 1: failures — stop, show output, user must fix.

2. **If infrastructure check fails**: The script output already contains actionable fix instructions. Present it verbatim. Do NOT compose your own explanation.

3. **If user asks for help**: Instruct them to add `GITLAB_HOST` and `TENANT` to `~/.conforma/.env`. If discovery still fails after that, instruct them to add `KONFLUX_CLUSTER_DOMAIN` to `~/.conforma/.env` manually.

## Notes

- All user-provided values go in `~/.conforma/.env` (gitignored, loaded automatically)
- Discovery cache TTL is 72 hours. Run `konflux_tenant_env_discovery.py --refresh` to force fresh discovery.
- VPN is required for discovery (GitLab access)
