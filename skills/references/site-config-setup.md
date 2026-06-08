# Site Config Setup — First-Run Consent Flow

Shared reference for skills that depend on site-config values. The agent follows this flow when `site_config.py --validate` reports missing variables.

## When to Use

Run this check at the start of any skill that needs infrastructure config (GitLab host, Konflux cluster domain, etc.). If all required variables are already set (from env vars, local config, or remote cache), this flow is skipped entirely.

## Flow

1. **Check**: Run `python3 scripts/site_config.py --validate`. If exit code 0, proceed with the skill.

2. **Inform**: If validation fails, tell the user:

   > This skill does not have any private or internal information built in. To connect to your infrastructure (GitLab, Konflux, Slack, etc.), it needs to learn hostnames, IPs, and other locations.
   >
   > There are two ways to provide this:
   >
   > 1. **Automatic**: I can try to fetch the team's site configuration from a private GitHub repository. This requires `gh` access to that repository.
   > 2. **Manual**: You can provide the values directly and I will save them locally.
   >
   > Which would you prefer?

   If `CONFORMA_SKILL_SITE_CONFIG_URL` is set, show that URL. Otherwise, mention the default location in `red-hat-data-services/rhods-devops-infra`.

3. **Automatic path**: Run `python3 scripts/site_config.py --refresh`.
   - On success: re-run `--validate` to confirm, then proceed with the skill.
   - On failure: explain the error (usually `gh` auth or repo access), offer the manual path as fallback.

4. **Manual path**: Ask the user for each missing variable. The required variables are:

   | Variable | YAML path | Description |
   |----------|-----------|-------------|
   | `GITLAB_HOST` | `gitlab.host` | Internal GitLab hostname |
   | `KRD_CLUSTER_DOMAIN` | `konflux.cluster_domain` | Konflux cluster domain segment |

   Optional variables (derive or ask if needed):

   | Variable | YAML path | Description |
   |----------|-----------|-------------|
   | `GITLAB_PROJECT` | `gitlab.project` | GitLab project path (default: `releng/konflux-release-data`) |
   | `KONFLUX_NAMESPACE` | `konflux.namespace` | Konflux tenant namespace |
   | `KONFLUX_EXTERNAL_API` | `konflux.external_api` | External Konflux API URL |
   | `SLACK_WORKSPACE_URL` | `slack.workspace_url` | Slack workspace base URL for search links |

   Once collected, save with:

   ```bash
   python3 scripts/site_config.py --write-local gitlab.host=VALUE konflux.cluster_domain=VALUE
   ```

5. **Verify**: Run `python3 scripts/site_config.py --show-source` to confirm where config was loaded from.

## Notes

- The agent MUST NOT silently fetch from a remote URL. Always inform and ask first.
- The `site_config.py` script is non-interactive — the consent layer is this reference, followed by the AI agent.
- Local config (`~/.config/aiops-infra/site-config.yaml`) always takes precedence over remote cache.
- Remote cache TTL is 72 hours. Run `--refresh` to force an update.
