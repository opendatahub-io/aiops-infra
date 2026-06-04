# Conforma Exception Process Reference

Self-contained documentation for the RHOAI Conforma exception request workflow.

## Jira Project Routing

All exception types require a **blocker RHOAIENG ticket** (cloned from template RHOAIENG-62569).
The secondary Jira project depends on the exception type:

| Exception type | Jira projects required |
|---|---|
| Self-service (non-security, release-specific) | RHOAIENG only |
| Security-related (non-hermetic, RPM signatures, SBOM) | RHOAIENG + PSX |
| FIPS-related | RHOAIENG + OCPEXCEPT |

## RHOAIENG Ticket Requirements

- Clone from template: [RHOAIENG-62569](https://redhat.atlassian.net/browse/RHOAIENG-62569)
- Priority: **Blocker**
- Label: `Exception - <full-exception-name>` (e.g., `Exception - hermetic_task.hermetic:quay.io/rhoai/odh-kserve-router-rhel9`)
- Assigned to the team responsible for root-cause remediation
- Target version set to the RHOAI release
- Must include remediation plan for each affected release

### Senior Manager Approval (rhoai-3.5-ea.1+)

For versions >= rhoai-3.5-ea.1, the RHOAIENG ticket requires approval from one of:
- Lindani Phiri
- Jay Koehler
- Sherard Griffin (or another member of Steven Huel's staff)

A comment on the ticket confirming approval is sufficient.

Versions before rhoai-3.5-ea.1 do NOT require senior manager approval.

## PSX Ticket (Security Exceptions)

For security-related exceptions (non-hermetic builds, RPM signatures, SBOM violations).

- Project: PSX
- Follow the [PSRD Exception Submission Quick Guide](https://redhat.atlassian.net/wiki/spaces/PRODSEC/pages/289226815/PSRD+Exception+Submission+Quick+Guide)
- Must reference the RHOAIENG ticket
- Requires Product Security team approval on the GitLab MR

## OCPEXCEPT Ticket (FIPS Exceptions)

For FIPS-related exceptions only. Replaces PSX (not needed in addition to PSX).

- Project: OCPEXCEPT
- Contact: Jean-Philippe Jung
- Must reference the RHOAIENG ticket

## Self-Service Exceptions

For non-security, RHOAI-release-specific exceptions. Only two rules qualify:
- `schedule.weekday_restriction` (weekend/Friday releases)
- `test.no_failed_tests:fbc-target-index-pruning-check` (catalog pruning)

These go to `exceptions/fbc-rhoai-prod.yaml` and are self-approved by the RHOAI team.
Still require a RHOAIENG blocker ticket (no PSX/OCPEXCEPT needed).

## Important Constraints

- **RPM signing keys cannot be added to the global allowed list.** The `allowed_rpm_signature_keys` list in Conforma is fixed. Third-party signing keys (e.g. AMD's `9386b48a`) can only be accommodated via per-component exceptions in the exception MR process. There is no mechanism to globally approve a new signing key.
- **Exceptions are the only path** for RPMs signed with keys not in the pre-defined allowed set, regardless of whether the key is legitimate and verifiable.

## Policy File Structure

### Standing Exceptions

Located under `config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy/`.
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
- [Konflux Policy Exceptions](https://konflux.pages.redhat.com/docs/users/releasing/policy-exceptions.html)
- [Konflux Release Troubleshooting](https://konflux.pages.redhat.com/docs/users/troubleshooting/releases.html)
- [Volatile Config (effectiveUntil)](https://conforma.dev/docs/policy/packages/release_volatile_config.html)
- [Schedule Weekday Restriction](https://conforma.dev/docs/policy/packages/release_schedule.html)
- [Conforma Release Policy — all enforced rules](https://conforma.dev/docs/policy/release_policy.html)
- [Conforma Release Policy — redhat collection rules](https://conforma.dev/docs/policy/release_policy.html#_available_rule_collections)
