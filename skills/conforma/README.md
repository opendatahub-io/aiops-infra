# Conforma Skills

AI-powered automation for RHOAI [Conforma](https://conforma.dev/docs/policy/release_policy.html) policy compliance -- violation analysis, exception management, release readiness, remediation, and documentation search.

This is the install guide for the full suite of `conforma-*` skills in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

## Install

### 1. Clone the repository

```bash
git clone https://github.com/opendatahub-io/aiops-infra.git
cd aiops-infra
```

### 2. Install Python dependencies

Requires **Python 3.11+**. Dependencies auto-install on first script run, but you can install upfront:

```bash
uv sync          # if you have uv
# or
pip install -e .
```

### 3. Configure secrets

```bash
cp .work/.env.example .work/.env
```

Open `.work/.env` and fill in the tokens:

| Variable | Where to get it |
|----------|-----------------|
| `GITHUB_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens) — scope: `repo` (needed for private `conforma-reporter`) |
| `GITLAB_TOKEN` | `https://$GITLAB_HOST/-/user_settings/personal_access_tokens` — scopes: `api`, `read_repository`, `write_repository` |
| `GITLAB_HOST` | Your internal GitLab hostname |
| `TENANT` | Your Konflux tenant name |
| `JIRA_API_TOKEN` | [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `JIRA_EMAIL` | Auto-derived from token on first run (or set manually) |

### 4. Verify setup

```bash
python3 scripts/verify_conforma_prerequisites.py --fix
```

This checks all dependencies, auth, and infrastructure discovery. The `--fix` flag prints remediation steps for any failures. All checks must pass before running workflows.
