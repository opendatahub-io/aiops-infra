# conforma-report-fetch

Fetch conforma reports from two sources -- CSV violation reports from the conforma-reporter GitHub repo, and raw EC JSON from Konflux PipelineRuns via the Tekton Results API.

This skill is part of the conforma suite. Follow the install instructions in [conforma/README.md](../conforma/README.md).

## Additional prerequisites (Tekton mode)

The Tekton JSON mode requires extra tools beyond the shared suite prerequisites:

- **VPN**: Connected to the corporate VPN
- **`oc` CLI**: Installed and authenticated to the Konflux cluster (`oc login --server=$KONFLUX_INTERNAL_API`)
- **`jq`**: Installed (used for JSON parsing)
- **Environment variables**: `TEKTON_RESULTS_API_DOMAIN`, `KONFLUX_NAMESPACE` (see SKILL.md for details)
