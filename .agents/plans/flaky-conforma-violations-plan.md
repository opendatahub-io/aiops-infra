# Plan: manage flaky Conforma violations caused by incomplete attestations

## Problem statement

An image such as `odh-th-torch-cuda-py312-v3-6-ea-2` can have a successful
image build while the Conforma report contains
`builtin.attestation.signature_check` with “no matching attestations”. One
possible explanation is that the image was pushed, but a later attestation
producer or prerequisite task (for example, a FIPS check) failed or has not
completed. In that case the Conforma row is a downstream symptom, not proof
that the component deliberately produced an unsigned image.

This plan is for investigation and implementation design. It does not assume
that the example is flaky until PipelineRun, Chains, registry, and Conforma
evidence agree.

## Desired outcome

For each missing-attestation violation, the analysis should classify the
condition deterministically as one of:

1. **Attestation present and valid** — stale or inconsistent report; rerun or
   investigate report generation.
2. **Attestation pending** — image/build exists, but the attestation-producing
   step or Chains processing is still in progress.
3. **Attestation blocked by upstream failure** — identify the failed task and
   expose its PipelineRun evidence, such as a failed FIPS task.
4. **Chains/registry failure** — the build completed, but Chains could not
   create or push the `.att` artifact.
5. **Policy/key mismatch** — an attestation exists but does not match the
   configured public key.
6. **Insufficient evidence** — do not call it flaky and do not recommend an
   exception; show exactly which source could not be checked.

The output should recommend the next deterministic action: wait and recheck,
rerun the relevant build/check, investigate Chains or registry permissions,
correct the policy key, or escalate an infrastructure issue.

## Evidence model

The classifier should correlate the following identifiers before making a
claim:

- image repository and immutable digest, not only the mutable tag;
- source Conforma report timestamp and PipelineRun name, where available;
- image build PipelineRun status and task results;
- FIPS task result and completion state, including the task name when present;
- `chains.tekton.dev/signed` annotation and relevant Chains error details;
- registry evidence for `.att` and `.sig` artifacts;
- EnterpriseContractPolicy public key identity;
- current raw Enterprise Contract result, when the scheduled CSV may be stale.

The classifier must distinguish “no attestation exists” from “attestation
exists but verification failed”. It must also distinguish a task that is
absent because it is intentionally not run from a task that was scheduled and
failed.

## Proposed implementation phases

### Phase 1 — establish the example and data contract

- Add a fixture representing the example image, its Conforma row, successful
  image build, failed or incomplete FIPS task, Chains annotation, and absent
  `.att` artifact.
- Document the exact Konflux/Tekton fields and API responses needed to correlate
  the image digest to its build and attestation activity.
- Decide whether the source of truth is the image digest’s build PipelineRun,
  a later verification PipelineRun, or both. Do not infer lineage from a tag
  alone.
- Define stable states and an evidence schema in the active Conforma context,
  retaining source URLs, timestamps, and raw status values for auditability.

### Phase 2 — add deterministic evidence collection

- Extend the report-fetch/investigation path with a read-only collector for:
  image metadata, candidate PipelineRuns, task results, Chains annotations,
  and attestation/signature artifact presence.
- Prefer existing Python/API primitives and the Tekton Results path; do not
  shell out to ad-hoc cluster commands when the same data can be retrieved by
  a library.
- Fail explicitly when a required source is unavailable. A missing API result
  must become **insufficient evidence**, not “flaky”.
- Record the collector result under its own context key and preserve the raw
  evidence location, following the existing `context.yaml` handover pattern.

### Phase 3 — implement classification

- Add a pure, unit-testable classifier that consumes normalized evidence and
  returns the state, confidence/evidence completeness, cause, and next action.
- Apply precedence rules so a failed upstream task wins over the generic
  “no matching attestations” symptom, while a successful Chains run with a
  missing artifact becomes a Chains/registry failure.
- Treat repeated appearance/disappearance across report history as supporting
  evidence only. Recurrence alone must not override current PipelineRun or
  registry evidence.
- Keep `builtin.attestation.signature_check` as a real Conforma violation;
  add a separate operational diagnosis rather than hiding or suppressing the
  policy result.

### Phase 4 — integrate presentation and remediation guidance

- Extend the violation catalog entry with the evidence-based diagnosis path,
  including upstream task failure and pending states.
- Update the generated resolution guide to show diagnosis, evidence links,
  report age, and the recommended retry/escalation action.
- Add explicit wording that exceptions are inappropriate for a transient or
  upstream pipeline condition unless the owning team confirms the image cannot
  be rebuilt through the supported path.
- Add a “recheck” operation that re-fetches current evidence and compares it
  with the prior diagnosis, so a later successful attestation can close the
  operational symptom without manual catalog edits.

### Phase 5 — validate against real historical cases

- Run the classifier on the named image and a representative set of cases:
  successful build with delayed Chains, failed FIPS task, Chains push/auth
  failure, key mismatch, valid attestation, and unavailable API.
- Compare classifications with owning-team review and record any ambiguous
  cases as fixtures rather than encoding assumptions in prose.
- Add integration coverage only for explicitly configured environments; unit
  tests must remain fully mocked and network-free.

## Tests required

- Normalization tests for image digest, PipelineRun, task, Chains, registry,
  and policy-key evidence.
- Classifier tests for every state above, including precedence when multiple
  failures coexist.
- Negative tests proving that missing evidence is not classified as flaky.
- History tests proving recurrence is supporting evidence, not the root cause.
- Rendering tests for the resolution guide and summary table, including links
  and a clear distinction between a policy violation and its operational
  diagnosis.
- Context handover tests proving failed evidence collection is represented
  explicitly and is not silently omitted.

## Decisions to make before implementation

1. Which API is authoritative for task-level FIPS status when the build
   PipelineRun has been pruned?
2. Can the registry check reliably inspect `.att` presence for private images,
   or must that result be supplied by a trusted Konflux/Chains API?
3. What age or state qualifies as **pending** before it becomes an operational
   failure requiring escalation?
4. Should recheck be automatic during report analysis, or an explicit command
   to avoid expensive and potentially rate-limited API calls?
5. Which team owns the diagnosis output and the escalation destination for
   Chains versus FIPS task failures?

## Non-goals

- Automatically suppressing `builtin.attestation.signature_check`.
- Automatically creating an exception, Merge Request, ticket, or other
  external change.
- Calling every missing attestation “flaky” based only on a single CSV row.
- Replacing the Conforma policy result with a locally inferred pass.

