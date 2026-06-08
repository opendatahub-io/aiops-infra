# conforma-report-fetch

Fetch conforma reports from two sources -- CSV violation reports from the conforma-reporter GitHub repo, and raw EC JSON from Konflux PipelineRuns via the Tekton Results API.

This skill is part of the conforma suite. Follow the install instructions in [conforma/README.md](../conforma/README.md).

## Additional prerequisites (Tekton mode)

The Tekton JSON mode requires extra tools beyond the shared suite prerequisites:

- **VPN**: Connected to the corporate VPN
- **`oc` CLI**: Installed and authenticated to the Konflux cluster (`oc login --server=https://api.stone-prod-p02.hjvn.p1.openshiftapps.com:6443`)
- **`jq`**: Installed (used for JSON parsing)
- **Namespace access**: Read access to the `rhoai-tenant` namespace
