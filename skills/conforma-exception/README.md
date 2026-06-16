# conforma-exception

End-to-end automation for RHOAI Conforma exception management: check existing exceptions, create new ones, extend effectiveUntil dates, validate inputs, create required Jira tickets (RHOAIENG + PSX/OCPEXCEPT), generate exception YAML, create GitLab MRs in `releng/konflux-release-data`, and cross-link all artifacts.

This skill is part of the conforma suite. Follow the install instructions in [conforma/README.md](../conforma/README.md).

See [SKILL.md](SKILL.md) for full agent usage documentation.

## Additional prerequisites

- **VPN access** to the internal GitLab instance (`$GITLAB_HOST`)

### Container fallback (advanced)

If `acli` auto-install fails (restricted network, unsupported platform), the scripts fall back to container images via docker/podman:

| Tool | Default image | Override env var |
|------|--------------|------------------|
| acli | `docker.io/davidsmith3/acli:latest` | `ACLI_IMAGE` |
| glab | `docker.io/gitlab/glab:latest` | `GLAB_IMAGE` |

Container mode requires API token authentication since `--web` OAuth cannot open the host browser from inside a container. See `verify_auth.py` output for container-specific auth instructions.
