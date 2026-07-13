# conforma-report-fetch

Fetch conforma reports from two sources -- CSV violation reports from the conforma-reporter GitHub repo, and raw EC JSON from Konflux PipelineRuns via the Tekton Results API.

This skill is part of the conforma suite. Follow the install instructions in [conforma/README.md](../conforma/README.md).

## Additional prerequisites (Tekton mode)

The Tekton JSON mode (`fetch_conforma_tekton_result.py`) requires:

- **VPN**: Connected to the corporate VPN
- **`oc` CLI**: Installed and authenticated to the Konflux cluster (`oc login --server=$KONFLUX_INTERNAL_API`)

When used with `context.yaml` (populated by `resolve_release_context.py`), no environment variables are needed. For standalone usage without context, configuration falls back to env vars (`KONFLUX_NAMESPACE`, `KONFLUX_CLUSTER_DOMAIN`, `KONFLUX_TOKEN`) and then to hardcoded defaults (p02 cluster, `rhoai-tenant` namespace).
