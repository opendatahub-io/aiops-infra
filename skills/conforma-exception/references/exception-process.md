# Conforma Exception Process Reference

Self-contained documentation for the RHOAI Conforma exception request workflow.

## Jira Project Routing

All exception types require up to three RHOAIENG tickets (the "three-ticket model").
The secondary Jira project depends on the exception type and environment.

### Three-Ticket Model

| Ticket | Issue Type | Priority | Summary Prefix | When Created |
|--------|-----------|----------|----------------|-------------|
| **Violation Report** | Bug | Blocker | `[Conforma Violation]` | Always (prod + stage) |
| **Remediation** | Bug | Blocker | `[Code Fix]` | Prod + stage (except self-service rules) |
| **Approval** | Task | Blocker | `[Exception Approval]` | Prod only |

### Workflow by Environment

| Exception type | Environment | Jira tickets |
|---|---|---|
| Self-service (weekday/fbc_pruning) | prod | Violation Report + MR |
| Self-service (weekday/fbc_pruning) | stage | Violation Report + MR (self-service) |
| Standard | stage | Violation Report + Remediation + MR (self-service) |
| Security-related | prod | Violation Report + Remediation + Approval + ProdSec form + MR |
| FIPS-related | prod | Violation Report + Remediation + Approval + OCPEXCEPT + MR |

### Shared Violation Report

The same violation report Jira should be used for both prod and stage exceptions for the same violation. It describes the problem and is not environment-specific.

## RHOAIENG Ticket Requirements

### Violation Report
- Issue type: **Bug**, priority: **Blocker**
- Summary prefix: `[Conforma Violation]`
- Label: `Exception - <full-exception-name>`
- `fixVersion` set to the target release for the fix (from `--fix-target-version`)

### Remediation
- Issue type: **Bug**, priority: **Blocker**
- Summary prefix: `[Code Fix]`
- Assigned to the team responsible for root-cause remediation
- References the violation report URL

### Approval
- Issue type: **Task**, priority: **Blocker**
- Summary prefix: `[Exception Approval]`
- Prod only — not created for stage exceptions

### Senior Manager Approval (rhoai-3.5-ea.1+)

For versions >= rhoai-3.5-ea.1, the RHOAIENG ticket requires approval from one of:
- Lindani Phiri
- Jay Koehler
- Sherard Griffin (or another member of Steven Huel's staff)

A comment on the ticket confirming approval is sufficient.

Versions before rhoai-3.5-ea.1 do NOT require senior manager approval.

## ProdSec Exception Form (Security Exceptions)

For security-related exceptions (non-hermetic builds, RPM signatures, SBOM violations).

The ProdSec team now uses a Google Form instead of direct PSX Jira ticket creation. The workflow is:

1. The skill generates a **pre-fill URL** with exception details populated from the violation data
2. The user opens the URL, reviews the form fields, and submits
3. A Jira ticket is created automatically by the form backend
4. The user provides the resulting ticket URL back to the skill via `--prodsec-ticket-url`
5. The skill continues with the GitLab MR and cross-linking

The form configuration is maintained in `scripts/prodsec_form_config.yaml`. See `references/update-prodsec-form.md` for instructions on updating it when a new form is released.

Legacy note: The `--psx-url` flag is kept as a backward-compatible alias for `--prodsec-ticket-url`. Existing PSX tickets from the old workflow are still supported for cross-linking.

## OCPEXCEPT Ticket (FIPS Exceptions)

For FIPS-related exceptions only. Replaces PSX (not needed in addition to PSX).

- Project: OCPEXCEPT
- Contact: Jean-Philippe Jung
- Must reference the RHOAIENG ticket

## Self-Service Exceptions

For non-security, RHOAI-release-specific exceptions. Only two rules qualify:
- `schedule.weekday_restriction` (weekend/Friday releases)
- `test.no_failed_tests:fbc-target-index-pruning-check` (catalog pruning)

These go to `exceptions/` directory files and are self-approved by the RHOAI team.
Still require a violation report RHOAIENG ticket. No remediation, approval, or PSX/OCPEXCEPT tickets needed.

## Stage Exceptions

Stage exceptions follow a simplified workflow:
- Drops the Approval Jira, ProdSec form, and PSX/OCPEXCEPT steps
- MR is self-service (targets `exceptions/` directory, self-mergeable)
- Still creates the Violation Report Jira (shared with prod)
- Creates the Remediation Jira unless the rule is self-service (weekday/fbc_pruning)
- MR titles are prefixed with `[stage]`

## Important Constraints

- **RPM signing keys cannot be added to the global allowed list.** The `allowed_rpm_signature_keys` list in Conforma is fixed. Third-party signing keys (e.g. AMD's `9386b48a`) can only be accommodated via per-component exceptions in the exception MR process. There is no mechanism to globally approve a new signing key.
- **Exceptions are the only path** for RPMs signed with keys not in the pre-defined allowed set, regardless of whether the key is legitimate and verifiable.

## Policy File Structure

### Standing Exceptions

Located under `config/${KONFLUX_CLUSTER_DOMAIN}/product/EnterpriseContractPolicy/`.
These are K8s `EnterpriseContractPolicy` resources. Exceptions go under:

```yaml
spec:
  sources:
    - name: Release Policies
      volatileConfig:
        exclude:
          - value: <rule>
            componentNames:
              - <component-name>
            effectiveUntil: "<RFC3339 timestamp>"
            reference: <jira-url>
```

### Self-Service Exceptions

Located under `exceptions/`. Flat YAML list format:

```yaml
---
- value: schedule.weekday_restriction
  imageRef: sha256:<digest>
```

## VolatileCriteria Schema

From the [EC controller spec](https://github.com/enterprise-contract/enterprise-contract-controller/blob/46c45526c2eda230cbc09ee080e2346c95e37be0/api/v1alpha1/policy_spec.json#L158):

- `value` (string, REQUIRED): policy rule being exempted
- `effectiveUntil` (date-time, optional): expiry in RFC3339 (`"2026-10-10T00:00:00Z"`)
- `effectiveOn` (date-time, optional): activation date
- `componentNames` (list of strings): Konflux component names (preferred for new entries)
- `imageUrl` (string, optional): image URL without tag
- `imageDigest` (sha256, optional): image by digest
- `imageRef` (sha256, optional): DEPRECATED, use imageDigest
- `reference` (string, optional): link to Jira issue

## Upstream Reference Links

- [PSRD Exception Process FAQ](https://redhat.atlassian.net/wiki/spaces/PRODSEC/pages/289252021/PSRD+Exception+Process+FAQ)
- [PSRD Exception Submission Quick Guide](https://redhat.atlassian.net/wiki/spaces/PRODSEC/pages/289226815/PSRD+Exception+Submission+Quick+Guide)
- [PSRD Exception Templates](https://redhat.atlassian.net/wiki/spaces/PRODSEC/pages/289256151/PSRD+Exception+Templates)
- [SSE Exception Process Documentation](https://redhat.atlassian.net/wiki/spaces/PRODSEC/pages/289157851/Secure+Software+Engagements+SSE+Exception+Process+Documentation)
- [Understanding Acceptance of Risk](https://redhat.atlassian.net/wiki/spaces/PRODSEC/pages/289208726/Understanding+Acceptance+of+Risk+as+an+Authorized+Party)
- Konflux Policy Exceptions (internal Konflux documentation — requires VPN)
- Konflux Release Troubleshooting (internal Konflux documentation — requires VPN)
- [Volatile Config (effectiveUntil)](https://conforma.dev/docs/policy/packages/release_volatile_config.html)
- [Schedule Weekday Restriction](https://conforma.dev/docs/policy/packages/release_schedule.html)
- [Conforma Release Policy — all enforced rules](https://conforma.dev/docs/policy/release_policy.html)
- [Conforma Release Policy — redhat collection rules](https://conforma.dev/docs/policy/release_policy.html#_available_rule_collections)
