"""Tests for scripts/verify_conforma_prerequisites.py — optional vs required checks."""

from __future__ import annotations

from unittest.mock import patch

import konflux_environment
import verify_conforma_prerequisites as prereqs


def _make_check(ok: bool, name: str, optional: bool = False, error: str | None = None, fix: str | None = None, detail: str | None = None) -> dict:
    result = {
        "ok": ok,
        "name": name,
        "optional": optional,
        "error": error if error else (None if ok else f"{name} failed"),
        "fix": fix if fix else (None if ok else f"fix {name}"),
    }
    if detail:
        result["detail"] = detail
    return result


class TestOptionalChecks:
    """Slack is optional — should not cause exit code 1."""

    def test_all_pass_returns_zero(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
            _make_check(True, "gitlab"),
            _make_check(True, "jira"),
            _make_check(True, "slack", optional=True),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 0

    def test_optional_fail_still_returns_zero(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
            _make_check(True, "gitlab"),
            _make_check(True, "jira"),
            _make_check(False, "slack", optional=True),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 0

    def test_required_fail_returns_one(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
            _make_check(False, "gitlab"),
            _make_check(True, "jira"),
            _make_check(False, "slack", optional=True),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 1

    def test_json_mode_ignores_optional_failures(self, capsys):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
            _make_check(True, "gitlab"),
            _make_check(True, "jira"),
            _make_check(False, "slack", optional=True),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py", "--json"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 0


class TestSlackCheckMarkedOptional:
    """Ensure the Slack check result always carries optional=True."""

    def test_slack_pass_is_optional(self):
        with patch("slack_ops.verify_auth", return_value={"ok": True, "team": "test", "team_url": "https://test.slack.com"}):
            result = prereqs._check_slack_auth()
        assert result["optional"] is True
        assert result["ok"] is True

    def test_slack_fail_is_optional(self):
        with patch("slack_ops.verify_auth", return_value={"ok": False, "error": "not installed"}):
            result = prereqs._check_slack_auth()
        assert result["optional"] is True
        assert result["ok"] is False


class TestFormatMarkdown:
    """Tests for the --format markdown output mode."""

    def test_all_pass_produces_table(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github", detail="user@example.com"),
            _make_check(True, "slack", optional=True, detail="team-x"),
        ]
        output = prereqs._format_markdown(results)
        assert "\u2705 Conforma Prerequisites \u2014 All Passed" in output
        assert "| python_deps | \u2705 Pass |" in output
        assert "| github | \u2705 Pass \u2014 user@example.com |" in output
        assert "| slack *(optional)* | \u2705 Pass \u2014 team-x |" in output
        assert "\u274c" not in output

    def test_failure_produces_sections(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(False, "github", fix="Add to ~/.conforma/.env:\n  GITHUB_TOKEN=ghp_xxx"),
        ]
        output = prereqs._format_markdown(results)
        assert "### \u2705 python_deps" in output
        assert "### \u274c github" in output
        assert "github failed" in output

    def test_failure_fix_has_code_block(self):
        results = [
            _make_check(False, "infra", fix="Add to ~/.conforma/.env:\n  GITLAB_HOST=my-host\n  TENANT=my-tenant"),
        ]
        output = prereqs._format_markdown(results)
        assert "```bash" in output
        assert "GITLAB_HOST=my-host" in output
        assert "TENANT=my-tenant" in output
        assert "```" in output

    def test_optional_warn_section(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(False, "slack", optional=True, error="not configured", fix="Run: bash scripts/install.sh"),
        ]
        output = prereqs._format_markdown(results)
        assert "### \u26a0\ufe0f slack *(optional)*" in output
        assert "not configured" in output

    def test_footer_shows_counts(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(False, "github"),
            _make_check(False, "slack", optional=True),
        ]
        output = prereqs._format_markdown(results)
        assert "1 passed" in output
        assert "1 failed" in output
        assert "1 warned (optional)" in output
        assert "Fix required checks before proceeding" in output

    def test_no_failures_footer_says_ready(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(False, "slack", optional=True),
        ]
        output = prereqs._format_markdown(results)
        assert "Ready to proceed" in output

    def test_main_markdown_format(self, capsys):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py", "--format", "markdown"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Conforma Prerequisites" in captured.out
        assert "All Passed" in captured.out


class TestIsCodeLine:
    """Tests for the _is_code_line heuristic."""

    def test_key_value_assignment(self):
        assert prereqs._is_code_line("GITLAB_HOST=my-host") is True
        assert prereqs._is_code_line("GITHUB_TOKEN=ghp_xxx") is True

    def test_shell_commands(self):
        assert prereqs._is_code_line("echo 'hello'") is True
        assert prereqs._is_code_line("python3 scripts/foo.py") is True
        assert prereqs._is_code_line("bash scripts/install.sh") is True
        assert prereqs._is_code_line("cp ~/.conforma/.env.example ~/.conforma/.env") is True
        assert prereqs._is_code_line("uv sync") is True

    def test_prose_is_not_code(self):
        assert prereqs._is_code_line("Then re-run this check") is False
        assert prereqs._is_code_line("Ensure VPN is connected") is False
        assert prereqs._is_code_line("(scope: api, read_repository)") is False


class TestFormatFixMarkdown:
    """Tests for fix text splitting into prose and code blocks."""

    def test_mixed_prose_and_code(self):
        fix = "Add to ~/.conforma/.env:\n  GITLAB_HOST=my-host\n  TENANT=my-tenant\nThen re-run."
        output = prereqs._format_fix_markdown(fix)
        assert "```bash" in output
        assert "GITLAB_HOST=my-host" in output
        assert "TENANT=my-tenant" in output
        assert "Then re-run." in output
        parts = output.split("```")
        assert len(parts) == 3  # before, inside, after

    def test_pure_prose(self):
        fix = "Fix the infrastructure check above first"
        output = prereqs._format_fix_markdown(fix)
        assert "```" not in output
        assert "Fix the infrastructure check above first" in output

    def test_pure_code(self):
        fix = "GITHUB_TOKEN=ghp_xxx"
        output = prereqs._format_fix_markdown(fix)
        assert "```bash" in output
        assert "GITHUB_TOKEN=ghp_xxx" in output


# ── GitLab error classification ─────────────────────────────────────────


class TestGitlabErrorClassification:
    """_check_gitlab_auth must classify errors: VPN vs missing-token vs expired-token."""

    DNS_ERROR = (
        "HTTPSConnectionPool(host='gitlab.corp.internal', port=443): Max retries exceeded "
        "with url: /api/v4/user (Caused by NameResolutionError(\"HTTPSConnection"
        "(host='gitlab.corp.internal', port=443): Failed to resolve 'gitlab.corp.internal' "
        "([Errno -2] Name or service not known)\"))"
    )

    CONNECTION_REFUSED_ERROR = "ConnectionRefusedError: [Errno 111] Connection refused"

    NETWORK_UNREACHABLE_ERROR = "OSError: [Errno 101] Network is unreachable"

    AUTH_REJECTED_ERROR = "GitlabAuthenticationError: 401 Unauthorized"

    @patch.dict("os.environ", {"GITLAB_HOST": "gitlab.corp.internal", "GITLAB_TOKEN": "glpat-old"}, clear=False)
    @patch("gitlab_ops.verify_auth", return_value={"ok": False, "error": DNS_ERROR})
    def test_dns_failure_reports_vpn(self, _mock):
        result = prereqs._check_gitlab_auth()
        assert result["ok"] is False
        assert "VPN CONNECTION REQUIRED" in result["fix"]
        assert "Cannot resolve gitlab.corp.internal" in result["fix"]

    @patch.dict("os.environ", {"GITLAB_HOST": "gitlab.corp.internal", "GITLAB_TOKEN": "glpat-old"}, clear=False)
    @patch("gitlab_ops.verify_auth", return_value={"ok": False, "error": CONNECTION_REFUSED_ERROR})
    def test_connection_refused_reports_vpn(self, _mock):
        result = prereqs._check_gitlab_auth()
        assert result["ok"] is False
        assert "VPN CONNECTION REQUIRED" in result["fix"]

    @patch.dict("os.environ", {"GITLAB_HOST": "gitlab.corp.internal", "GITLAB_TOKEN": "glpat-old"}, clear=False)
    @patch("gitlab_ops.verify_auth", return_value={"ok": False, "error": NETWORK_UNREACHABLE_ERROR})
    def test_network_unreachable_reports_vpn(self, _mock):
        result = prereqs._check_gitlab_auth()
        assert result["ok"] is False
        assert "VPN CONNECTION REQUIRED" in result["fix"]

    @patch.dict("os.environ", {"GITLAB_HOST": "gitlab.corp.internal"}, clear=False)
    @patch("gitlab_ops.verify_auth", return_value={"ok": False, "error": AUTH_REJECTED_ERROR})
    def test_no_token_reports_missing(self, _mock):
        env = {"GITLAB_HOST": "gitlab.corp.internal"}
        with patch.dict("os.environ", env, clear=True):
            result = prereqs._check_gitlab_auth()
        assert result["ok"] is False
        assert "No GitLab token found" in result["fix"]
        assert "VPN" not in result["fix"]

    @patch.dict("os.environ", {"GITLAB_HOST": "gitlab.corp.internal", "GITLAB_TOKEN": "glpat-old"}, clear=False)
    @patch("gitlab_ops.verify_auth", return_value={"ok": False, "error": AUTH_REJECTED_ERROR})
    def test_expired_token_reports_regenerate(self, _mock):
        result = prereqs._check_gitlab_auth()
        assert result["ok"] is False
        assert "token exists but is invalid or expired" in result["fix"]
        assert "VPN" not in result["fix"]

    @patch.dict("os.environ", {"GITLAB_HOST": "gitlab.corp.internal", "GITLAB_TOKEN": "glpat-good"}, clear=False)
    @patch("gitlab_ops.verify_auth", return_value={"ok": True, "user": "wznoinsk"})
    @patch.object(konflux_environment, "check_connectivity")
    def test_success_returns_ok(self, _mock_conn, _mock_auth):
        result = prereqs._check_gitlab_auth()
        assert result["ok"] is True
        assert result["detail"] == "Authenticated as: wznoinsk"


# ── Jira error classification ───────────────────────────────────────────


class TestJiraErrorClassification:
    """_check_jira_auth must classify errors: VPN vs missing-credentials vs expired-token."""

    DNS_ERROR = (
        "HTTPSConnectionPool(host='redhat.atlassian.net', port=443): Max retries exceeded "
        "with url: /rest/api/2/myself (Caused by NameResolutionError(\"HTTPSConnection"
        "(host='redhat.atlassian.net', port=443): Failed to resolve 'redhat.atlassian.net' "
        "([Errno -2] Name or service not known)\"))"
    )

    AUTH_401_ERROR = (
        "JiraError HTTP 401 url: https://redhat.atlassian.net/rest/api/2/myself\n"
        "\ttext: Client must be authenticated to access this resource."
    )

    CONNECTION_REFUSED_ERROR = "ConnectionRefusedError: [Errno 111] Connection refused"

    @patch("jira_ops.verify_auth", return_value={"ok": False, "error": DNS_ERROR})
    def test_dns_failure_reports_vpn(self, _mock):
        with patch.dict("os.environ", {"JIRA_API_TOKEN": "tok", "JIRA_EMAIL": "a@b.com"}, clear=False):
            result = prereqs._check_jira_auth()
        assert result["ok"] is False
        assert "VPN CONNECTION REQUIRED" in result["fix"]
        assert "Cannot reach Jira" in result["fix"]

    @patch("jira_ops.verify_auth", return_value={"ok": False, "error": CONNECTION_REFUSED_ERROR})
    def test_connection_refused_reports_vpn(self, _mock):
        with patch.dict("os.environ", {"JIRA_API_TOKEN": "tok", "JIRA_EMAIL": "a@b.com"}, clear=False):
            result = prereqs._check_jira_auth()
        assert result["ok"] is False
        assert "VPN CONNECTION REQUIRED" in result["fix"]

    @patch("jira_ops.verify_auth", return_value={"ok": False, "error": AUTH_401_ERROR})
    def test_no_credentials_reports_missing(self, _mock):
        env = {"HOME": "/tmp"}
        with patch.dict("os.environ", env, clear=True):
            result = prereqs._check_jira_auth()
        assert result["ok"] is False
        assert "No Jira credentials found" in result["fix"]
        assert "VPN" not in result["fix"]

    @patch("jira_ops.verify_auth", return_value={"ok": False, "error": AUTH_401_ERROR})
    def test_expired_token_reports_regenerate(self, _mock):
        with patch.dict("os.environ", {"JIRA_API_TOKEN": "old-token", "JIRA_EMAIL": "me@rh.com"}, clear=False):
            result = prereqs._check_jira_auth()
        assert result["ok"] is False
        assert "token exists but is invalid or expired" in result["fix"]
        assert "VPN" not in result["fix"]

    @patch("jira_ops.verify_auth", return_value={"ok": True, "user": "wznoinsk"})
    def test_success_returns_ok(self, _mock):
        result = prereqs._check_jira_auth()
        assert result["ok"] is True
        assert result["detail"] == "Authenticated as: wznoinsk"


# ── Konflux connectivity checks ─────────────────────────────────────────


class TestKonfluxConnectivity:
    """_check_konflux must probe DNS + HTTPS against the cluster API host."""

    BASE_ENV = {
        "KONFLUX_TENANT": "my-tenant",
        "KONFLUX_CLUSTER_DOMAIN": "test-cluster-01.abc.xyz",
    }

    @patch.dict("os.environ", BASE_ENV, clear=False)
    @patch.object(prereqs, "_probe_konflux_cluster", return_value=(True, True, None))
    @patch.object(konflux_environment, "_check_konflux_connectivity")
    def test_cluster_reachable_and_authenticated(self, mock_oc, _mock_probe):
        def side_effect(result):
            result.konflux_reachable = True
        mock_oc.side_effect = side_effect
        result = prereqs._check_konflux()
        assert result["ok"] is True
        assert "authenticated" in result["detail"]
        assert "test-cluster-01" in result["detail"]

    @patch.dict("os.environ", BASE_ENV, clear=False)
    @patch.object(prereqs, "_probe_konflux_cluster", return_value=(
        False, False, "Cannot resolve host: [Errno -2] Name or service not known",
    ))
    def test_dns_failure_reports_vpn(self, _mock_probe):
        result = prereqs._check_konflux()
        assert result["ok"] is False
        assert "VPN CONNECTION REQUIRED" in result["fix"]
        assert "test-cluster-01" in result["fix"]

    @patch.dict("os.environ", BASE_ENV, clear=False)
    @patch.object(prereqs, "_probe_konflux_cluster", return_value=(
        True, False, "Cannot connect to host:6443: timed out",
    ))
    def test_https_failure_reports_vpn(self, _mock_probe):
        result = prereqs._check_konflux()
        assert result["ok"] is False
        assert "DNS resolves but HTTPS connection failed" in result["fix"]

    @patch.dict("os.environ", BASE_ENV, clear=False)
    @patch.object(prereqs, "_probe_konflux_cluster", return_value=(True, True, None))
    @patch.object(konflux_environment, "_check_konflux_connectivity")
    def test_network_ok_but_not_authenticated(self, mock_oc, _mock_probe):
        def side_effect(result):
            result.konflux_reachable = False
            result.error_details["konflux"] = (
                "error: You must be logged in to the server (Unauthorized)"
            )
        mock_oc.side_effect = side_effect
        result = prereqs._check_konflux()
        assert result["ok"] is False
        assert "reachable but not authenticated" in result["fix"]
        assert "oc login" in result["fix"]
        assert "VPN" not in result["fix"]

    @patch.dict("os.environ", BASE_ENV, clear=False)
    @patch.object(prereqs, "_probe_konflux_cluster", return_value=(True, True, None))
    @patch.object(konflux_environment, "_check_konflux_connectivity")
    def test_no_cli_but_network_reachable(self, mock_oc, _mock_probe):
        def side_effect(result):
            result.konflux_reachable = None
        mock_oc.side_effect = side_effect
        result = prereqs._check_konflux()
        assert result["ok"] is True
        assert "reachable" in result["detail"]
        assert "test-cluster-01" in result["detail"]


class TestProbeKonfluxCluster:
    """_probe_konflux_cluster must classify DNS vs HTTPS failures."""

    def test_dns_failure(self):
        import socket
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
            dns_ok, https_ok, error = prereqs._probe_konflux_cluster("api.fake.host")
        assert dns_ok is False
        assert https_ok is False
        assert "Cannot resolve" in error

    def test_https_success(self):
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with (
            patch("socket.getaddrinfo", return_value=[("fake",)]),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            dns_ok, https_ok, error = prereqs._probe_konflux_cluster("api.fake.host")
        assert dns_ok is True
        assert https_ok is True
        assert error is None

    def test_http_error_counts_as_success(self):
        import urllib.error
        with (
            patch("socket.getaddrinfo", return_value=[("fake",)]),
            patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
                "https://api.fake:6443/healthz", 401, "Unauthorized", {}, None,
            )),
        ):
            dns_ok, https_ok, error = prereqs._probe_konflux_cluster("api.fake.host")
        assert dns_ok is True
        assert https_ok is True
        assert error is None

    def test_ssl_error_counts_as_success(self):
        import urllib.error
        with (
            patch("socket.getaddrinfo", return_value=[("fake",)]),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError(
                "CERTIFICATE_VERIFY_FAILED",
            )),
        ):
            dns_ok, https_ok, error = prereqs._probe_konflux_cluster("api.fake.host")
        assert dns_ok is True
        assert https_ok is True
        assert error is None

    def test_connection_timeout(self):
        import urllib.error
        with (
            patch("socket.getaddrinfo", return_value=[("fake",)]),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError(
                "timed out",
            )),
        ):
            dns_ok, https_ok, error = prereqs._probe_konflux_cluster("api.fake.host")
        assert dns_ok is True
        assert https_ok is False
        assert "Cannot connect" in error


# ── Quay.io auth checks ───────────────────────────────────────────────


class TestFindQuayAuth:
    """Tests for _find_quay_auth — locating quay.io credentials in auth config."""

    def test_finds_auth_in_docker_config(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text('{"auths": {"quay.io": {"auth": "dGVzdDp0ZXN0"}}}')
        with patch.object(prereqs, "_QUAY_AUTH_CONFIG_PATHS", [config]):
            auth, path = prereqs._find_quay_auth()
        assert auth == "dGVzdDp0ZXN0"
        assert path == config

    def test_returns_none_when_no_config(self, tmp_path):
        with patch.object(prereqs, "_QUAY_AUTH_CONFIG_PATHS", [tmp_path / "nonexistent.json"]):
            auth, path = prereqs._find_quay_auth()
        assert auth is None
        assert path is None

    def test_returns_none_when_no_quay_entry(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text('{"auths": {"docker.io": {"auth": "abc123"}}}')
        with patch.object(prereqs, "_QUAY_AUTH_CONFIG_PATHS", [config]):
            auth, path = prereqs._find_quay_auth()
        assert auth is None
        assert path is None

    def test_tries_multiple_paths(self, tmp_path):
        missing = tmp_path / "missing.json"
        present = tmp_path / "present.json"
        present.write_text('{"auths": {"quay.io": {"auth": "found"}}}')
        with patch.object(prereqs, "_QUAY_AUTH_CONFIG_PATHS", [missing, present]):
            auth, path = prereqs._find_quay_auth()
        assert auth == "found"
        assert path == present

    def test_handles_malformed_json(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text("not json")
        with patch.object(prereqs, "_QUAY_AUTH_CONFIG_PATHS", [config]):
            auth, path = prereqs._find_quay_auth()
        assert auth is None


class TestCheckQuayAuth:
    """Tests for _check_quay_auth — the full quay.io preflight check (Bearer token flow)."""

    def _mock_token_and_api(self, tmp_path, *, token_status=200, api_status=200,
                            token_json=None, token_exc=None, api_exc=None):
        """Helper: set up auth config and mock requests.get (token) + requests.head (API)."""
        import requests as req_mod
        from unittest.mock import MagicMock

        config = tmp_path / "config.json"
        config.write_text('{"auths": {"quay.io": {"auth": "dGVzdDp0ZXN0"}}}')

        token_resp = MagicMock(status_code=token_status)
        if token_json is None:
            token_json = {"token": "bearer-test-token"}
        token_resp.json.return_value = token_json

        api_resp = MagicMock(status_code=api_status)

        patches = [patch.object(prereqs, "_QUAY_AUTH_CONFIG_PATHS", [config])]
        if token_exc:
            patches.append(patch.object(req_mod, "get", side_effect=token_exc))
        else:
            patches.append(patch.object(req_mod, "get", return_value=token_resp))
        if api_exc:
            patches.append(patch.object(req_mod, "head", side_effect=api_exc))
        else:
            patches.append(patch.object(req_mod, "head", return_value=api_resp))

        return patches

    def test_ok_when_auth_valid(self, tmp_path):
        patches = self._mock_token_and_api(tmp_path, token_status=200, api_status=200)
        with patches[0], patches[1], patches[2]:
            result = prereqs._check_quay_auth()
        assert result["ok"] is True
        assert result["name"] == "quay"

    def test_fails_when_no_auth_config(self, tmp_path):
        with patch.object(prereqs, "_QUAY_AUTH_CONFIG_PATHS", [tmp_path / "nonexistent.json"]):
            result = prereqs._check_quay_auth()
        assert result["ok"] is False
        assert "quay.io authentication is required" in result["error"]
        assert "podman login quay.io" in result["fix"]

    def test_fails_when_token_401(self, tmp_path):
        patches = self._mock_token_and_api(tmp_path, token_status=401)
        with patches[0], patches[1], patches[2]:
            result = prereqs._check_quay_auth()
        assert result["ok"] is False
        assert "invalid or expired" in result["error"]

    def test_fails_when_api_403(self, tmp_path):
        patches = self._mock_token_and_api(tmp_path, token_status=200, api_status=403)
        with patches[0], patches[1], patches[2]:
            result = prereqs._check_quay_auth()
        assert result["ok"] is False
        assert "lack access" in result["error"]

    def test_fails_on_token_network_error(self, tmp_path):
        import requests as req_mod
        patches = self._mock_token_and_api(
            tmp_path, token_exc=req_mod.ConnectionError("timeout"))
        with patches[0], patches[1], patches[2]:
            result = prereqs._check_quay_auth()
        assert result["ok"] is False
        assert "connectivity" in result["error"]

    def test_fails_on_api_network_error(self, tmp_path):
        import requests as req_mod
        patches = self._mock_token_and_api(
            tmp_path, api_exc=req_mod.ConnectionError("timeout"))
        with patches[0], patches[1], patches[2]:
            result = prereqs._check_quay_auth()
        assert result["ok"] is False
        assert "connectivity" in result["error"]

    def test_fails_when_token_empty(self, tmp_path):
        patches = self._mock_token_and_api(tmp_path, token_json={"token": ""})
        with patches[0], patches[1], patches[2]:
            result = prereqs._check_quay_auth()
        assert result["ok"] is False
        assert "no token" in result["error"]

    def test_is_required_not_optional(self):
        """Quay auth must NOT be marked optional — it's a hard stop."""
        with patch.object(prereqs, "_find_quay_auth", return_value=(None, None)):
            result = prereqs._check_quay_auth()
        assert result.get("optional") is not True

    def test_quay_in_run_all_checks(self):
        """Ensure _check_quay_auth is registered in run_all_checks."""
        source = prereqs.run_all_checks.__code__
        import dis
        called_names = set()
        for instr in dis.get_instructions(source):
            if instr.opname == "LOAD_GLOBAL" or instr.opname == "LOAD_ATTR":
                called_names.add(instr.argval)
        assert "_check_quay_auth" in called_names
