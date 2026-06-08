# Conforma Skills

AI-powered automation for RHOAI [Conforma](https://conforma.dev/docs/policy/release_policy.html) policy compliance -- violation analysis, exception management, release readiness, remediation, and documentation search.

This is the master install and setup guide for the full suite of `conforma-*` skills in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

## Install

Install all conforma skills (via skills-registry):

- **Cursor**: `cursor skills install opendatahub-io/aiops-infra`
- **Claude Code**: `claude install-skill opendatahub-io/aiops-infra`

Python dependencies are auto-installed on first run.

## Prerequisites

### CLI tools (install once)

| Tool | Purpose | Install |
|------|---------|---------|
| `gh` | GitHub CLI | [cli.github.com](https://cli.github.com) |
| `glab` | GitLab CLI | Fedora/RHEL: `sudo dnf install glab` / macOS: `brew install glab` |
| `acli` | Jira (Atlassian) CLI | Auto-installed on first use -- no manual install needed |

### One-time authentication

Credentials persist across sessions. Run these once after installing the CLI tools:

1. **GitHub**:

```bash
gh auth login
```

2. **Jira**: generate an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens), then:

```bash
echo "YOUR_TOKEN" | acli jira auth login --site redhat.atlassian.net --email "$USER@redhat.com" --token
```

3. **GitLab**: go to [gitlab.cee.redhat.com/-/user_settings/personal_access_tokens](https://gitlab.cee.redhat.com/-/user_settings/personal_access_tokens), create a token named `glab-cli` with `api` scope and 1 year expiration, then:

```bash
glab auth login --hostname gitlab.cee.redhat.com --token "YOUR_TOKEN"
```

### Additional requirements

Some skills require extra tools or access beyond the shared set above. See each skill's own README for details.

| Skill | Extra requirements |
|-------|--------------------|
| `conforma-analyze` | `GITHUB_TOKEN` with read access to `red-hat-data-services/conforma-reporter` (private) |
| `conforma-report-fetch` | Tekton mode: `oc` CLI, `jq`, VPN access |
| `conforma-exception` | VPN access to `gitlab.cee.redhat.com` |
| `conforma-release-readiness` | Read access to `conforma-reporter` (private) |

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

## Troubleshooting

If you run into authentication issues, the suite includes dedicated troubleshooting skills:

- **GitLab**: use the `gitlab-auth` skill
- **Jira**: use the `jira-auth` skill
- **GitHub**: use the `github-auth` skill
