# conforma-analyze

Fetch and parse RHOAI Conforma violation report data from [conforma-reporter](https://github.com/red-hat-data-services/conforma-reporter). Trace when specific violations appeared or disappeared via CSV git history.

This skill is part of the conforma suite. Follow the install instructions in [conforma/README.md](../conforma/README.md).

## Quick start

```bash
# 1. One-time setup (if not done already):
cp .work/.env.example .work/.env   # fill in tokens
.work/bin/slackdump login          # opens browser for Red Hat SSO (auto-installed on first use)

# 2. Verify all prerequisites pass:
python3 scripts/verify_conforma_prerequisites.py --fix

# 3. Use the skill via AI assistant:
#    "what's the conforma status for rhoai-3.4?"
```

## Additional prerequisites

- `GITHUB_TOKEN` with read access to `red-hat-data-services/conforma-reporter` (private repo)
- VPN active (for GitLab-based component catalog enrichment and coverage check)
- All auth checked by `verify_conforma_prerequisites.py` before workflow runs
