# Cover real-world policy exception matcher variations

Status: **NOT STARTED**

Related plan: [aiops-infra shared Conforma policy exception matcher and scoped mutation](/home/wznoinsk/.claude/plans/aiops-infra-shared-conforma-policy-exception-matcher.md)

## Goal

Ensure the shared Conforma policy exception parser and matcher covers the real
exception formats used across current and historical production policy files,
not only the RHOAI 3.6 EA1 base-image examples.

## Evidence collected

The workflow-managed `konflux-release-data` tree contains these relevant forms:

- Exact unquoted values, such as `hermetic_task.hermetic`.
- Exact single-quoted and double-quoted values.
- Parameterized unquoted values, such as
  `rpm_signature.allowed:05b555b38483c65d`.
- Parameterized single-quoted and double-quoted values, including
  `base_image_registries.base_image_permitted:<registry-path>`.
- Long parameterized package-source values containing URLs, query strings,
  checksums, ampersands, and additional colons.
- Component-scoped exceptions using `componentNames`.
- Unscoped exceptions without `componentNames`.
- Image-scoped exceptions using `imageUrl`.
- A self-service exception using `imageRef`.
- Permanent exclusions under `exclude`, which must remain distinct from
  time-bounded `volatileCriteria` exceptions.

All current policy value entries observed in the checked tree use ten-space
indentation. Historical examples include RHOAI, Red Hat Developer Hub, DPU
Kit, OCP ART, OVE, and other product policy files.

Relevant historical commits include `c03a123d4`, `a31019a82`, `edd6cda12`,
`4f999e669`, and `de4cf1af7`.

## Required matching semantics

- An exact query `rule` matches only `rule` or a policy value beginning with
  `rule:`; it must not match `rule-other`.
- A full query `rule:suffix` matches only that exact normalized value.
- Single-quoted, double-quoted, and unquoted values normalize to the same
  comparison value.
- The suffix after the first `rule:` separator is preserved verbatim as the
  extra argument, including registry paths, URLs, query strings, and colons.
- Each exception retains its full value, base rule, extra argument,
  `componentNames`, `imageUrl` or `imageRef`, `effectiveUntil`, file, and line.
- Permanent `exclude` entries and scoped or time-bounded `volatileCriteria`
  entries remain separate result types.

## Verification

- Add fixtures based on real policy shapes for every form listed above.
- Test exact, quoted, parameterized, URL-bearing, component-scoped, unscoped,
  `imageUrl`, and `imageRef` values.
- Test that multiple suffixes for one base rule remain distinct.
- Test that a base-rule query does not match a similarly named rule without a
  colon separator.
- Test both the current RHOAI 3.6 EA1 policy entries and historical-style
  entries from other product policies.
- Run the shared parser, coverage, exception scanner, and TODO renderer tests.
- Maintain at least 97% line, branch, and statement coverage for modified
  scripts where the repository coverage checks support those metrics.

## Definition of done

- The shared matcher handles all observed production and historical formats.
- The RHOAI 3.6 EA1 base-image exceptions are recognized as covering the
  affected component.
- Component scope and extra arguments are available to coverage and TODO
  rendering.
- Permanent, volatile, and self-service exception forms are not conflated.
- Regression fixtures and focused tests pass.
