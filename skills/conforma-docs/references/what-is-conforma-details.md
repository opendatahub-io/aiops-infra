# Conforma — Detailed Concepts

## Violations

A violation is a policy rule that a component's build failed to satisfy. Violations come in two severities: FAILURE (blocking — the release cannot proceed) and WARNING (non-blocking — noted but does not block). See the full list of enforced rules in the [Conforma release policy](https://conforma.dev/docs/policy/release_policy.html).

```
Rule: hermetic_task.hermetic
Type: FAILURE
Message: Task 'buildah' was not invoked with the hermetic parameter set
Component: my-component-v2-1
```

This violation tells you that the `buildah` build task for the `my-component-v2-1` component ran without network isolation. The [Conforma](https://conforma.dev) rule [`hermetic_task.hermetic`](https://conforma.dev/docs/policy/packages/release_hermetic_task.html#hermetic_task__hermetic) checks the [PipelineRun](https://tekton.dev/docs/pipelines/pipelineruns/) attestation for the `HERMETIC` parameter on the build task. When it is missing or set to `false`, the task could have fetched undeclared dependencies from the internet during the build, which undermines supply chain integrity. Because this is a FAILURE-level rule, it blocks the release until resolved.

## Remedies

A remedy is a fix applied to the component's source code, Dockerfile, or build pipeline definition that resolves the root cause of a violation. Remedies are always preferred over exceptions because they permanently eliminate the violation for all future builds.

```yaml
# .tekton/my-component-push.yaml (Pipelines-as-Code definition)
tasks:
  - name: buildah
    params:
      - name: IMAGE
        value: "$(params.output-image)"
      - name: HERMETIC
        value: "true"
```

This is the fix for the `hermetic_task.hermetic` violation shown above. By adding `HERMETIC: "true"` to the `buildah` task's params in the component's [Pipelines-as-Code](https://pipelinesascode.com) YAML, the next build will run in hermetic mode (no network access during the build step). All dependencies must then be pre-fetched via the `prefetch-dependencies` task, ensuring they are declared and included in the [SBOM](https://www.ntia.gov/page/software-bill-materials). Once this change is merged and a new build triggers, the Conforma verification will pass for this rule.

## Exceptions

An exception is a temporary waiver that allows a component to pass Conforma verification despite having an active violation. Exceptions are stored as YAML blocks in the `konflux-release-data` GitLab repository's policy files, using the [VolatileCriteria](https://conforma.dev/docs/policy/packages/release_volatile_config.html) schema. The specific policy file paths are derived from your site config's `KRD_CLUSTER_DOMAIN` setting.

```yaml
# EnterpriseContractPolicy/<your-policy-file>.yaml
- rule: hermetic_task.hermetic
  effectiveUntil: "2026-10-05T00:00:00Z"
  componentNames:
    - my-component-v2-1
```

This exception waives the `hermetic_task.hermetic` rule for the `my-component-v2-1` component until October 5, 2026. After that date, the exception expires and the violation will block the release again. Every exception requires ProdSec approval and a linked remediation Jira ticket with a plan to fix the underlying issue. Exceptions are a last resort — remedies are always preferred.

## Release Readiness

[Conforma](https://conforma.dev) acts as a release gate: a product version can only ship when every component passes verification — meaning all FAILURE-level violations across all components are either resolved (via remedy) or covered by a valid, non-expired exception.

```
Product v2.1 Release Readiness:
  model-registry-v2-1:
    hermetic_task.hermetic     — VIOLATION (no exception)    ← BLOCKS RELEASE
    rpm_signature.allowed:9386b48a — VIOLATION (exception until 2026-10-05)  ✓
  dashboard-v2-1:
    All rules passed                                          ✓
  controller-v2-1:
    All rules passed                                          ✓

Verdict: CANNOT SHIP — 1 unresolved violation
```

This readiness summary shows 3 components for a product release. `model-registry-v2-1` has two violations: one for hermetic builds (no exception — this blocks the release) and one for an RPM signed with a third-party key (covered by an exception valid until October 2026 — this is fine). The other two components pass all rules. The overall verdict is "cannot ship" because one violation has no remedy and no exception. The team must either fix the hermetic build issue or obtain an approved exception before the release can proceed.
