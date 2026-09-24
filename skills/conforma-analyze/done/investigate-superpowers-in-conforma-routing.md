# Investigate unexpected superpowers involvement in Conforma requests

Status: **DONE — repository guardrail added; external loader remains out of scope**

## Outcome

The unexpected `using-superpowers` involvement is not caused by Conforma
routing. The `conforma` router sends ordinary report/status/violation requests
to `conforma-analyze`, and neither the router nor the analysis skill references
`using-superpowers`. The process skill is selected by the agent-level startup
contract, which is outside this repository.

The path failure was caused by treating the catalog alias `r0` as a literal
directory. In this environment the authoritative mapping is:

```text
r0 = /home/wznoinsk/.codex/skills
r0/using-superpowers/SKILL.md
  -> /home/wznoinsk/.codex/skills/using-superpowers/SKILL.md
```

The expanded path exists; `/home/wznoinsk/.codex/skills/r0` does not.

## Changes

- Added an explicit alias-expansion contract to `AGENTS.md`. Agents must use
  the mapped root and must report the expanded path when resolution fails.
- Added `tests/unit/test_skill_routing_contract.py` to prevent Conforma from
  acquiring a process-skill dependency and to keep the alias rule present.
- Preserved the deterministic Conforma routing and script-failure behavior.

No loader source or skill-root configuration is present in this repository or
in the local Codex configuration, so the external loader itself cannot be
patched here. The repository guardrail prevents this repository's instructions
from reintroducing the same path interpretation and records the limitation.

## Verification

- Confirmed `skills/conforma/SKILL.md` routes ordinary reports to
  `conforma-analyze` and contains no `using-superpowers` reference.
- Confirmed the valid `using-superpowers/SKILL.md` path exists and the literal
  `r0` directory does not.
- Added focused routing/contract regression tests.
- A fresh agent session is required to verify behavior of the external loader;
  that cannot be simulated by a repository-only test.
