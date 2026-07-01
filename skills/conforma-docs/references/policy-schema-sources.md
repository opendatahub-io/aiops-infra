# Conforma Policy Schema Sources

The Conforma policy configuration schema is split across two upstream repositories. The Kubernetes CRD defines the top-level structure, while the Rego policy rules define the shape of freeform fields like `ruleData`.

## CRD layer — config, volatileConfig, VolatileCriteria

- **Repository**: https://github.com/conforma/crds
- **Canonical file**: `api/v1alpha1/enterprisecontractpolicy_types.go`

Each `Source` in the `EnterpriseContractPolicy` spec has:

| Field | Type | What it controls |
|-------|------|------------------|
| `config` | `SourceConfig` | Simple `include`/`exclude` string arrays for policy rules |
| `volatileConfig` | `VolatileSourceConfig` | Time-bounded `include`/`exclude` with `VolatileCriteria` entries |
| `ruleData` | `*extv1.JSON` | Arbitrary JSON — schema enforced by Rego at evaluation time, not by the CRD |

### VolatileCriteria fields

| Field | Type | Description |
|-------|------|-------------|
| `value` | string | **Required** — the policy rule identifier |
| `effectiveOn` | date-time | When the criteria becomes active |
| `effectiveUntil` | date-time | When the criteria expires |
| `imageDigest` | sha256 string | Scope to a specific image digest |
| `imageUrl` | string | Scope to an image URL (without tag) |
| `componentNames` | string list | Scope to specific Konflux component names |
| `reference` | string | Link to related info (e.g. Jira issue URL) |
| `imageRef` | sha256 string | **DEPRECATED** — use `imageDigest` |

Only one of `imageUrl`, `imageDigest`, `imageRef`, or `componentNames` may be set per entry.

## Rego policy layer — ruleData schemas

`ruleData` is freeform JSON at the CRD level. Its internal structure is defined and validated by Rego policy rules at evaluation time.

- **Repository**: https://github.com/conforma/policy
- **Schema validation pattern**: search for `j.validate_schema(rule_data.get(...), { ... })` calls in Rego files

### Example: `disallowed_attributes`

Defined in `policy/lib/sbom/sbom.rego`:

```yaml
disallowed_attributes:              # list of objects (ruleData key)
  - name: string                    # required — attribute name to match
    value: string                   # optional — attribute value to match
    effective_on: string            # optional — date-time
    except_when:                    # optional — list of exception conditions
      - purl_qualifier: string      # required — which PURL qualifier to inspect
        patterns:                   # required — list of regex patterns
          - "^https://..."          # violation suppressed if qualifier value matches any pattern
```

The suppression logic is in `disallowed_attribute_excepted()` in the same file.

### How to find the schema for any ruleData key

1. Clone `https://github.com/conforma/policy`
2. `grep -rn "key_name" --include="*.rego"` to find where it is consumed
3. Look for the `j.validate_schema(...)` call near the usage — it contains the JSON Schema definition
4. Check the corresponding `*_test.rego` file for usage examples

The CRD will never constrain `ruleData` — it is always validated by Rego rules at policy evaluation time.
