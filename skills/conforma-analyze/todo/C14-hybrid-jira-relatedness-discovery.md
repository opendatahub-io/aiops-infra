# C14 — Hybrid discovery of Conforma-related Jira tickets

Status: **NOT STARTED**

Depends on: C11; integrates with C13 independent labelling

## Goal

Extend Jira coverage so label-less tickets can be discovered as potentially
related to the Conforma violations being analyzed, including
RHOAIENG-70681. Use deterministic code for retrieval, normalization, matching,
and write safety. Use a large language model only as an advisory adjudicator
for candidates that deterministic rules cannot classify confidently.

## Current state

The existing `conforma_jira_ticket_ops.py` implementation provides part of the
deterministic foundation:

- label-first discovery across the configured Jira projects and statuses;
- additional rule/component text candidates when current violation data is
  supplied to `discover_conforma_tickets`;
- exact unique violation-label searches;
- Merge Request-reference lookup and retrieval of referenced Jira tickets;
- deterministic rule-plus-component matching;
- unit-test coverage containing RHOAIENG-70681 as a closed prior issue.

The following pieces are missing:

- standalone broad discovery of label-less tickets;
- Jira comment and issue-history evidence retrieval;
- a normalized evidence bundle with source and match explanations;
- confidence and ambiguity handling;
- large-language-model adjudication for genuinely ambiguous candidates;
- independent presentation and confirmation of proposed labels.

## Proposed flow

### 1. Build deterministic search candidates

Search the configured Jira projects using violation-derived signals, not only
labels:

- exact and normalized Conforma rule codes;
- rule aliases and violation-message terms;
- version-stripped Konflux component names;
- mapped Jira component names;
- release and environment identifiers;
- known Jira keys from current data, prior runs, and Merge Request references.

Use bounded, auditable JQL/search passes. Record each query, result count,
pagination state, and any failed source. A successful empty result must remain
distinct from a failed or unauthorized search.

### 2. Retrieve evidence for each candidate

Fetch and normalize the fields needed for adjudication:

- key, project, issue type, status, labels, summary, description;
- Jira components, target version, fix versions, and links;
- comments and relevant issue history when permissions allow;
- matching Conforma rules, messages, releases, environments, and components;
- related Merge Request references and their source locations.

Retain source URLs and field-level evidence. If comments or history cannot be
read, record that limitation instead of treating the fields as empty.

### 3. Apply deterministic classification first

Return structured classifications such as:

- `confirmed_conforma_violation`;
- `confirmed_conforma_general`;
- `possible_conforma_related`;
- `unrelated`;
- `insufficient_evidence`.

The deterministic classifier should explain every match and apply conservative
thresholds. A ticket must not receive `conforma-violation` solely because it
contains the word “Conforma”. Existing exception-ticket safeguards must remain
in force.

### 4. Adjudicate only ambiguous candidates

For `possible_conforma_related` candidates, optionally send a minimal,
redacted evidence bundle to a configured large-language-model provider. Require
a structured response containing:

- relatedness decision: `violation`, `general`, `unrelated`, or `uncertain`;
- matched rule, component, release, and evidence references;
- confidence and reasons;
- explicit acknowledgement of missing evidence.

The model must not call Jira, modify labels, create tickets, or override a
deterministic negative result. Provider failure, malformed output, or low
confidence becomes `insufficient_evidence` and is reported for review.

The default workflow must remain usable without a model provider. Model use
must be opt-in/configured, observable, and covered by mocked tests.

### 5. Present and label independently

Produce a read-only report showing each candidate, classification, evidence,
proposed labels, and unresolved ambiguity. The labelling action from C13 must
consume this report independently of ticket creation or Jira sync. Once C14 is
implemented, the standard workflow must invoke C13 for the candidates produced
here, including candidates that were not found by label-first discovery.

Before any Jira write, require explicit confirmation and then add labels
additively with set-then-verify behavior. Preserve unrelated labels and record
success, verification failure, and API failure separately.

## RHOAIENG-70681 acceptance case

- Retrieve the ticket without relying on existing labels.
- Show which rule, component, release, description, comment, or related
  Merge Request evidence connects it to the observed Conforma violation.
- Classify it as a prior violation only when the evidence supports that claim.
- If the evidence is insufficient, report it as ambiguous rather than applying
  labels automatically.
- Add regression fixtures for the live field shape, including its empty-label
  state.

## Tests and validation

- Unit-test each deterministic search pass, pagination, deduplication, and
  failure-versus-empty distinction.
- Test normalization of Jira fields, comments, history, rule aliases,
  component stems, releases, and Merge Request references.
- Test deterministic classification boundaries and exception-ticket safeguards.
- Test model-provider payload construction, schema validation, timeout/error
  handling, low-confidence results, and provider-disabled behavior with mocks.
- Test that model output cannot cause a Jira write or override a deterministic
  negative classification.
- Test independent C13 labelling when ticket creation and Jira sync are
  disabled or failed.
- Run a live read-only audit for RHOAIENG-70681 and other label-less candidates
  before proposing any label changes.

## Dependencies and decisions

- C13 independent labelling action.
- Decide which Jira projects and issue statuses are in scope for broad search.
- Decide whether comments/history may be sent to the configured model provider
  and what redaction is required.
- Choose the supported model provider and structured-output contract, if model
  adjudication is enabled.
- Define confidence thresholds and the required human review path.
- Confirm whether closed tickets should receive labels.

## Definition of done

- Label-less related tickets are discoverable without weakening auth/error
  handling or silently returning incomplete results.
- Each candidate has deterministic evidence and a reproducible classification.
- Ambiguous candidates can be adjudicated by a configured model, but model
  failure never produces an automatic label or pass.
- C13 can label independently of creation and sync.
- C14 automatically feeds its confirmed candidates to C13 during the standard
  workflow, subject to the existing confirmation-before-write rule.
- RHOAIENG-70681 is either confirmed with evidence or explicitly reported as
  insufficient evidence, with tests covering the outcome.
- Read-only audit, confirmation, additive writes, and set-then-verify behavior
  are documented and tested.
