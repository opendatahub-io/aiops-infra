# Conforma Skills

AI-powered automation for RHOAI [Conforma](https://conforma.dev/docs/policy/release_policy.html) policy compliance -- violation analysis, exception management, release readiness, remediation, and documentation search.

This is the master install and setup guide for the full suite of `conforma-*` skills in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

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
| `JIRA_API_TOKEN` | [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `JIRA_EMAIL` | Auto-derived from token on first run (or set manually) |

### 4. Authenticate Slack (for coverage search)

slackdump is auto-installed to `.work/bin/` on first use. You only need to log in once:

```bash
.work/bin/slackdump login    # opens browser for Red Hat SSO
```

If slackdump hasn't been installed yet (e.g. first time running the verify script), trigger it manually:

```bash
bash scripts/install_slackdump.sh
.work/bin/slackdump login
```

### 5. Verify everything works

```bash
python3 scripts/verify_conforma_prerequisites.py --fix
```

This single command checks: Python deps, `.work/.env`, infrastructure discovery, GitHub auth, GitLab auth (requires VPN), Jira auth, and Slack auth. All must pass before running workflows. The `--fix` flag prints remediation steps for any failures.

## Infrastructure Discovery

Infrastructure details (Konflux cluster domain, API URLs, Conforma policy paths, RPA directories) are discovered automatically from the `konflux-release-data` GitLab repository. You only need to provide two values — a GitLab hostname and a tenant name.

### Setup: Add to .work/.env

```
GITLAB_HOST=your-gitlab-host
TENANT=your-tenant-name
```

On the next run, `konflux_tenant_env_discovery.py` auto-discovers `KONFLUX_CLUSTER_DOMAIN` and all derived variables. Results are cached for 72 hours.

To verify discovery works:

```bash
python3 scripts/konflux_tenant_env_discovery.py --tenant YOUR_TENANT --human
```

### If discovery fails

If auto-discovery cannot work in your environment (e.g. no VPN, tenant not registered), add the required variables to `.work/.env` manually:

```
KONFLUX_CLUSTER_DOMAIN=your-cluster-domain
```

## Skills in the suite

| Skill | Purpose |
|-------|---------|
| [`conforma`](../conforma/) | Entry-point router -- detects intent and routes to the appropriate skill |
| [`conforma-analyze`](../conforma-analyze/) | Fetch and parse violation reports, trace history |
| [`conforma-report-fetch`](../conforma-report-fetch/) | Fetch reports: CSV from GitHub, JSON from Tekton |
| [`conforma-exception`](../conforma-exception/) | Create, extend, manage, and review policy exceptions |
| [`conforma-release-readiness`](../conforma-release-readiness/) | "Can version X ship?" -- detailed breakdown and verdict |
| [`conforma-remedy`](../conforma-remedy/) | Fix violations in component code, configs, or build pipelines |
| [`conforma-docs`](../conforma-docs/) | Full-text search across Conforma documentation and runbooks |
| [`conforma-feedback`](../conforma-feedback/) | Report issues or feedback about Conforma skills |

## Additional per-skill requirements

Some skills require extra access or VPN connectivity beyond the shared set above:

| Skill | Extra requirements |
|-------|--------------------|
| `conforma-analyze` | `GITHUB_TOKEN` with read access to `conforma-reporter` (private) |
| `conforma-report-fetch` | Tekton mode: `oc` CLI, `jq`, VPN access |
| `conforma-exception` | VPN access to internal GitLab |
| `conforma-release-readiness` | Read access to `conforma-reporter` (private) |

## Troubleshooting

If you run into authentication issues, the suite includes dedicated troubleshooting skills:

- **GitLab**: use the `gitlab-auth` skill
- **Jira**: use the `jira-auth` skill
- **GitHub**: use the `github-auth` skill
- **Slack**: use the `slack-auth` skill

Or run the prerequisite checker for a full diagnostic:

```bash
python3 scripts/verify_conforma_prerequisites.py --fix
```
