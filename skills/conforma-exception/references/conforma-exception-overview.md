# What Is a Conforma Exception?

A **Conforma exception** is a policy waiver in the [Conforma](https://conforma.dev/docs/policy/release_policy.html) release policy engine used by Red Hat's Konflux CI/CD platform. It tells the policy engine to **skip enforcement of a specific rule** for listed components until a given expiry date.

Concretely, an exception is a YAML entry added to a Conforma Policy file in the `konflux-release-data` GitLab repository (hosted on the internal GitLab instance at `$GITLAB_HOST`), following the [VolatileCriteria](https://conforma.dev/docs/policy/packages/release_volatile_config.html) schema:

```yaml
# https://redhat.atlassian.net/browse/RHOAIENG-12345
# impacted versions: rhoai-3.4
- value: hermetic_task.hermetic
  componentNames:
    - odh-model-server-v3-4
    - odh-modelmesh-serving-v3-4
  effectiveUntil: "2026-10-05T00:00:00Z"
  reference: https://redhat.atlassian.net/browse/PSX-1234
```

Key fields:

- **`value`** — the Conforma rule being waived (e.g. `hermetic_task.hermetic`, `rpm_signature.allowed:...`, `fips-check`)
- **`componentNames`** — the Konflux component names the waiver applies to. Conforma also supports `imageUrl` for scoping by container image reference, but this skill exclusively uses `componentNames` for precision and maintainability
- **`effectiveUntil`** — the expiry date in RFC 3339 format, after which the rule is enforced again
- **`reference`** — the PSX or OCPEXCEPT Jira ticket URL that authorized the exception through the Product Security approval workflow

## Approval Workflow

Creating a Conforma exception in the RHOAI context involves a multi-step approval workflow:

1. **RHOAIENG component bugfix Jira ticket** — documents the plan to fix the underlying violation in the component code (e.g. make the component build hermetic, or switch to only approved sources of packages)
2. **RHOAIENG Senior Management approval Jira ticket** — gets RHOAI Management sign-off on granting the exception
3. **PSX or OCPEXCEPT Jira ticket** — the exception request that follows the Product Security workflow of approvals
4. **GitLab Merge Request** — adds the YAML exception entry to the Conforma Policy in konflux-release-data

## Time-Bound Nature

Exceptions are time-bound by design — they exist to unblock a release while the underlying issue is being resolved, and they stop being effective automatically after the `effectiveUntil` date.
