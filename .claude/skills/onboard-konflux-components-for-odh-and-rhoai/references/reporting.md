# Print Final Summary

```
=== onboard-konflux-components-for-odh-and-rhoai — Run Complete ===

  Component      : <COMPONENT_NAME>
  Product        : <PRODUCT_CONTEXT>
  Jira           : <JIRA_URL>

PRs / MRs:
  quay            : <steps.quay.status> — <steps.quay.mr_url or "not yet raised">
  slack_handle    : <steps.slack_handle.status> — <steps.slack_handle.pr_url or "not yet raised">
  krd             : <steps.krd.status> — <steps.krd.mr_url or "not yet raised">
  okc             : <steps.okc.status> — <steps.okc.pr_url or "not yet raised">
  pull_pipelines  : <steps.pull_pipelines.status or "N/A (ODH)">
  operator        : <steps.operator.status>
  bundle          : <steps.bundle.status>
  krd_rpa         : <steps.krd_rpa.status or "N/A (ODH)"> — <steps.krd_rpa.mr_url or "not yet raised">
  delivery_repo   : <steps.delivery_repo.status or "N/A (ODH)">
  product_listing : <steps.product_listing.status or "N/A (ODH)">
  auto_merge      : <steps.auto_merge.status or "N/A (ODH)">
  renovate        : <steps.renovate.status or "N/A (ODH)">
  renovate_sync   : <steps.renovate_sync.status or "N/A (ODH)">
  onboarder_workflow: <steps.onboarder_workflow.status or "N/A (RHOAI)">
  component_repo_map: <steps.component_repo_map.status or "N/A (ODH)"> — <steps.component_repo_map.pr_url or "no PR (already correct on main)">

Newly merged this run : <NEWLY_MERGED or "none">
State file            : $PIPELINE_STATE

Re-run this skill after PRs/MRs are merged to advance the pipeline.
```

---

## Error Reference

Common failures: credential not set → export the var; tool missing → install per Step 1; YAML missing → run `/create-component-onboarding-jira` first; YAML invalid → fix, re-upload, re-run; VPN down → activate VPN, re-run. GitLab MR failures → check VPN + `GITLAB_TOKEN` scopes (`api`, `write_repository`). GitHub PR failures → check `GITHUB_TOKEN` `repo` scope and push access. Onboarder workflow 422 → krd/okc not yet merged. Build verify timeout/failure → check PAC config or build URL. State lost → re-run; Step 5 restores from Jira labels.
