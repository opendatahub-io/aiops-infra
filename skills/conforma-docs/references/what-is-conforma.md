# What Is Conforma?

## Conforma: The Policy Engine

[Conforma](https://conforma.dev) (formerly called Enterprise Contract, or EC) is a policy verification engine that enforces release rules on container images built by [Konflux](https://konflux.dev), Red Hat's CI/CD platform. Every component image must pass Conforma verification before it can be included in a product release.

## Where Conforma Fits in the Release Pipeline

Conforma runs as a `verify` task inside a Konflux release [PipelineRun](https://tekton.dev/docs/pipelines/pipelineruns/). It is not part of the build itself — it runs after the image is built, signed, and attested. The policy engine examines the build attestation — a signed [SLSA](https://slsa.dev) provenance document that records everything about how the image was produced (the source commit, the build tasks that ran, whether the build had network access, the full list of packages pulled in such as RPMs, Python packages, Go modules, and npm dependencies, plus the resulting [SBOM](https://www.ntia.gov/page/software-bill-materials)) — to check whether the build process followed the required practices.

```text
┌─ Build (Konflux / Tekton) ───────────────────┐   ┌─ Provenance ──────────┐
│                                               │   │                       │
│  ┌────────┐    ┌───────────┐    ┌──────────┐  │   │  ┌─────────────────┐  │
│  │ Source ─┼───▶│ prefetch- ┼───▶│ buildah  ┼──┼───┼─▶│ Sign image +   │  │
│  │ code   │    │ deps      │    │ (build)  │  │   │  │ SLSA attestation│  │
│  └────────┘    └───────────┘    └──────────┘  │   │  └────────┬────────┘  │
│                                               │   │           │           │
└───────────────────────────────────────────────┘   └───────────┼───────────┘
                                                                │
┌─ Release Pipeline ────────────────────────────────────────────┼───────────┐
│                                                               │           │
│   ┌───────────────────┐        ╔══════════════╗               │           │
│   │ Policy rules      │·······▶║   CONFORMA   ║◀──────────────┘           │
│   │ (redhat, from     │        ║  verify task ║                           │
│   │  conforma.dev)    │ ┌·····▶║              ║                           │
│   └───────────────────┘ ·      ╚══════╤═══════╝                           │
│   ┌───────────────────┐ ·             │                                   │
│   │ Exceptions        │·┘      ┌──────┴──────┐                            │
│   │ (konflux-release- │        │             │                            │
│   │  data, GitLab)    │        ▼             ▼                            │
│   └───────────────────┘ ┌──────────┐  ┌───────────┐                      │
│                         │ RELEASE  │  │  RELEASE  │                      │
│                         │ to       │  │  BLOCKED  │                      │
│                         │ registry │  │           │                      │
│                         └──────────┘  └───────────┘                      │
│                          all rules     FAILURE violations                │
│                          pass or       without exceptions                │
│                          excepted                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

The build pipeline produces a container image with a signed [SLSA](https://slsa.dev) attestation. Conforma evaluates this attestation against the [`redhat` rule collection](https://conforma.dev/docs/policy/release_policy.html), cross-referenced with any approved exceptions in the `konflux-release-data` GitLab repo. If all rules pass (or violations are covered by valid exceptions), the release proceeds. Otherwise, the release is blocked.

Many teams also run Conforma verification on a recurring schedule (e.g. daily) via a reporter workflow that creates snapshots of all component images for each active release, evaluates them against the same policy rules, and posts violation reports. This provides a continuous view of release readiness between actual releases, allowing teams to catch and address violations before they become release blockers.

## Your Environment

The specific infrastructure details — which Konflux cluster, which GitLab instance hosts `konflux-release-data`, which reporter workflow to use — are **auto-discovered** from your GitLab host and Konflux tenant name. This keeps the skills portable across products and teams. Run `python3 scripts/verify_conforma_prerequisites.py --fix` to check your setup. If auto-discovery doesn't work, add the required variables to `~/.conforma/.env` manually.

## Key Concepts

- **Violations** — a policy rule that a component's build failed to satisfy. FAILURE-level violations block the release; WARNING-level ones do not.
- **Remedies** — fixes to the component's source, Dockerfile, or build pipeline that resolve the root cause. Always preferred over exceptions.
- **Exceptions** — temporary waivers for violations that cannot be fixed immediately, stored in `konflux-release-data` with expiration dates and ProdSec approval.
- **Release readiness** — a product version can only ship when every component's FAILURE-level violations are either remedied or covered by a valid exception.

Ask about any of these concepts to see details and examples.
