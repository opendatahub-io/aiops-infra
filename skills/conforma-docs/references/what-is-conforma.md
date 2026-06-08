# What Is Conforma?

## Conforma: The Policy Engine

Conforma (formerly called Enterprise Contract, or EC) is a policy verification engine that enforces release rules on container images built by [Konflux](https://konflux.dev), Red Hat's CI/CD platform. In the RHOAI (Red Hat OpenShift AI) context, every component image must pass Conforma verification before it can be included in a release.

```
PipelineRun: conforma-registry-rhoai-prod-v3-5-model-registry-abc123
  Task: verify
  Status: FAILURE
  Violations: 2
  Warnings: 1
```

This is the output summary from a Conforma verification run inside a Konflux release pipeline. `conforma-registry-rhoai-prod-v3-5-model-registry-abc123` is the PipelineRun name — it encodes the product (`rhoai`), environment (`prod`), version (`v3-5`), and component (`model-registry`). The `verify` task ran the Conforma policy engine against the built image's attestation and found 2 blocking violations and 1 non-blocking warning. The 2 violations must be resolved (or covered by an exception) before this component can ship.

## Where Conforma Fits in the Release Pipeline

Conforma runs as a `verify` task inside a Konflux release PipelineRun. It is not part of the build itself — it runs after the image is built, signed, and attested. The policy engine examines the build attestation (a signed SLSA provenance document) to check whether the build process followed the required practices.

```
Source code  →  Build (Tekton)  →  Sign + Attest  →  Conforma verify  →  Release
                                                          ↑
                                                   Policy rules from
                                                   conforma.dev/redhat
                                                   collection
```

The build pipeline produces a container image along with a signed attestation that records what happened during the build: which tasks ran, what parameters they used, what base images were pulled, and what packages were included. Conforma then evaluates this attestation against the `redhat` rule collection. If all rules pass (or violations are covered by exceptions), the release proceeds. If any rule produces a FAILURE-level violation without an exception, the release is blocked.

## Violations

A violation is a policy rule that a component's build failed to satisfy. Violations come in two severities: FAILURE (blocking — the release cannot proceed) and WARNING (non-blocking — noted but does not block).

```
Rule: hermetic_task.hermetic
Type: FAILURE
Message: Task 'buildah' was not invoked with the hermetic parameter set
Component: odh-model-server-v3-5
```

This violation tells you that the `buildah` build task for the `odh-model-server-v3-5` component ran without network isolation. The Conforma rule `hermetic_task.hermetic` checks the PipelineRun attestation for the `HERMETIC` parameter on the build task. When it is missing or set to `false`, the task could have fetched undeclared dependencies from the internet during the build, which undermines supply chain integrity. Because this is a FAILURE-level rule, it blocks the release until resolved.

## Remedies

A remedy is a fix applied to the component's source code, Dockerfile, or build pipeline definition that resolves the root cause of a violation. Remedies are always preferred over exceptions because they permanently eliminate the violation for all future builds.

```yaml
# .tekton/model-server-push.yaml (PipelineAs-Code definition)
tasks:
  - name: buildah
    params:
      - name: IMAGE
        value: "$(params.output-image)"
      - name: HERMETIC
        value: "true"
```

This is the fix for the `hermetic_task.hermetic` violation shown above. By adding `HERMETIC: "true"` to the `buildah` task's params in the component's PipelineAs-Code YAML, the next build will run in hermetic mode (no network access during the build step). All dependencies must then be pre-fetched via the `prefetch-dependencies` task, ensuring they are declared and included in the SBOM. Once this change is merged and a new build triggers, the Conforma verification will pass for this rule.

## Release Readiness

Conforma acts as a release gate: a version of RHOAI can only ship when every component passes verification — meaning all FAILURE-level violations across all components are either resolved (via remedy) or covered by a valid, non-expired exception.

```
RHOAI v3.5 Release Readiness:
  model-registry-v3-5:
    hermetic_task.hermetic     — VIOLATION (no exception)    ← BLOCKS RELEASE
    rpm_signature.allowed:9386b48a — VIOLATION (exception until 2026-10-05)  ✓
  odh-dashboard-v3-5:
    All rules passed                                          ✓
  odh-notebook-controller-v3-5:
    All rules passed                                          ✓

Verdict: CANNOT SHIP — 1 unresolved violation
```

This readiness summary shows 3 components for RHOAI v3.5. `model-registry-v3-5` has two violations: one for hermetic builds (no exception — this blocks the release) and one for an RPM signed with a third-party key (covered by an exception valid until October 2026 — this is fine). The other two components pass all rules. The overall verdict is "cannot ship" because one violation has no remedy and no exception. The team must either fix the hermetic build issue or obtain an approved exception before the release can proceed.
