# Error reference

| Error | Step | Action |
|-------|------|--------|
| Invalid Jira URL format | 0 | Correct the URL and re-run |
| `JIRA_USER_EMAIL` / `JIRA_API_TOKEN` not set | 0 | Export the env vars |
| `uv` not installed | 0 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `jq` not installed | 2 | `brew install jq` or `sudo dnf install jq` |
| Jira fetch fails (401/403/404) | 2 | Check credentials and issue key |
| Repository not found / not accessible (non-200 HTTP) | Q4-check | Create the GitHub repository first, then re-run |
| YAML generation fails | 5 | Check arguments; see stderr from `generate_onboarding_yaml.py` |
| YAML validation fails | 6 | Correct the inputs and re-generate |
| Dockerfile digest violations found | 6b | Pin all FROM images with @sha256 digests, then re-run |
| Clone fails (ODH: `RHAI-58088`, RHOAI: `RHAI-58087`) | 7b-1 | Check `JIRA_USER_EMAIL` / `JIRA_API_TOKEN`; verify create permission |
| "relates to" link type not found | 7-pre, 7b-1 | Check available link types with a Jira admin |
| Attach/upload fails | 7, 7b-2 | Check credentials; re-run the skill |
| Metadata update fails | 7c | Warnings printed; update title/description/label manually in Jira |
