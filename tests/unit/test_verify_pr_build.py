"""The RHOAI PR-build verifier creates, verifies, and cleans up a dummy PR."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_pr_build.sh"


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _mock_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    _write(
        bin_dir / "oc",
        """
        #!/usr/bin/env bash
        case "$*" in
          "whoami --show-server") echo "https://api.stone-prod-p01.wcfb.p1.openshiftapps.com:6443" ;;
          "whoami --show-token") echo "test-token" ;;
          "whoami") echo "tester" ;;
          *) exit 0 ;;
        esac
        """,
    )

    _write(
        bin_dir / "uv",
        """
        #!/usr/bin/env bash
        echo "$*" >> "${UV_LOG:?}"
        exit 0
        """,
    )

    _write(
        bin_dir / "curl",
        r"""
        #!/usr/bin/env bash
        method="GET"
        url=""
        write_out=""
        out_target=""
        args=("$@")
        for ((i=0; i<${#args[@]}; i++)); do
          case "${args[$i]}" in
            -X) method="${args[$((i+1))]}" ;;
            -w) write_out="${args[$((i+1))]}" ;;
            -o) out_target="${args[$((i+1))]}" ;;
            http*) url="${args[$i]}" ;;
          esac
        done

        body=""
        status=200
        case "$method $url" in
          "GET https://api.github.com/repos/red-hat-data-services/sample")
            body='{"default_branch":"main"}'
            ;;
          "GET "*"/contents/.tekton/odh-sample-pull-request.yaml?ref=main")
            body='{}'
            ;;
          "GET "*"/pulls?state=open&per_page=100")
            body='[]'
            ;;
          "GET "*"/pulls/42")
            body='{"state":"open","html_url":"https://github.com/red-hat-data-services/sample/pull/42"}'
            ;;
          "GET "*"/git/ref/heads/main")
            body='{"object":{"sha":"abc123"}}'
            ;;
          "POST "*"/git/refs")
            body='{"ref":"refs/heads/test"}'
            ;;
          "PUT "*"/contents/"*)
            body='{"content":{"sha":"def456"}}'
            ;;
          "POST "*"/pulls")
            body='{"number":42,"html_url":"https://github.com/red-hat-data-services/sample/pull/42"}'
            ;;
          "GET "*"pipelineruns?labelSelector="*)
            pr_status="${MOCK_PR_STATUS:-True}"
            pr_reason="Succeeded"
            if [[ "$pr_status" != "True" ]]; then
              pr_status="Unknown"
              pr_reason="Running"
            fi
            body="{\"items\":[{\"metadata\":{\"name\":\"odh-sample-on-pull-request-42\",\"creationTimestamp\":\"2026-01-01T00:00:00Z\",\"annotations\":{\"build.appstudio.redhat.com/pull_request_number\":\"42\"},\"labels\":{\"appstudio.openshift.io/application\":\"rhoai-v3-7-ea-1\"}},\"status\":{\"conditions\":[{\"type\":\"Succeeded\",\"status\":\"${pr_status}\",\"reason\":\"${pr_reason}\"}]}}]}"
            ;;
          "PATCH "*"/pulls/42")
            body='{"state":"closed"}'
            ;;
          "DELETE "*"/git/refs/heads/"*)
            body='{}'
            ;;
          *)
            body='{"message":"unexpected mock request"}'
            status=500
            ;;
        esac

        echo "$method $url" >> "${CURL_LOG:?}"
        if [[ "$out_target" == "/dev/null" ]]; then
          printf '%s' "$status"
        elif [[ "$out_target" == "/dev/stdout" ]]; then
          printf '%s%s' "$body" "$status"
        else
          printf '%s' "$body"
        fi
        """,
    )

    return bin_dir


def _run(tmp_path: Path, *, pr_status: str, timeout: str = "5"):
    bin_dir = _mock_bin(tmp_path)
    workdir = tmp_path / "work"
    curl_log = tmp_path / "curl.log"
    curl_log.write_text("", encoding="utf-8")
    uv_log = tmp_path / "uv.log"
    uv_log.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "GITHUB_TOKEN": "test-token",
            "CURL_LOG": str(curl_log),
            "UV_LOG": str(uv_log),
            "WORKDIR": str(workdir),
            "TMPDIR": str(tmp_path),
            "PR_BUILD_TIMEOUT": timeout,
            "PR_BUILD_INTERVAL": "1",
            "TEKTON_SYNC_TIMEOUT": "1",
            "MOCK_PR_STATUS": pr_status,
        }
    )

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--jira-url",
            "https://redhat.atlassian.net/browse/RHOAIENG-103708",
            "--component-name",
            "odh-sample",
            "--version-var",
            "v3-7-ea-1",
            "--repo-url",
            "https://github.com/red-hat-data-services/sample",
            "--repo-branch",
            "main",
            "--workdir",
            str(workdir),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result, workdir, curl_log, uv_log


def test_verifies_pr_build_and_cleans_up(tmp_path: Path):
    result, workdir, curl_log, uv_log = _run(tmp_path, pr_status="True")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Pull-request build verified" in result.stdout
    assert not (workdir / "pr_build_verify.json").exists()
    calls = curl_log.read_text(encoding="utf-8")
    assert "POST https://api.github.com/repos/red-hat-data-services/sample/pulls" in calls
    assert "PATCH https://api.github.com/repos/red-hat-data-services/sample/pulls/42" in calls
    assert "DELETE https://api.github.com/repos/red-hat-data-services/sample/git/refs/heads/" in calls
    # The mock must receive the Jira comment call: the real `uv` would post
    # fixture values to the production ticket.
    assert "update_jira_issue.py" in uv_log.read_text(encoding="utf-8")


def test_timeout_keeps_pr_for_retry_and_retry_reuses_it(tmp_path: Path):
    first, workdir, _, first_uv = _run(tmp_path, pr_status="running", timeout="0")
    assert first.returncode == 1
    assert "update_jira_issue.py" in first_uv.read_text(encoding="utf-8")
    state = workdir / "pr_build_verify.json"
    assert state.exists()
    assert '"pr_number": 42' in state.read_text(encoding="utf-8")

    second, _, curl_log, second_uv = _run(tmp_path, pr_status="True")
    assert second.returncode == 0, second.stdout + second.stderr
    assert not state.exists()
    assert "Reusing existing verification PR #42" in second.stderr
    calls = curl_log.read_text(encoding="utf-8")
    # The retry must not open a second PR.
    assert calls.count("POST https://api.github.com/repos/red-hat-data-services/sample/pulls") == 0
    assert "DELETE https://api.github.com/repos/red-hat-data-services/sample/git/refs/heads/" in calls
    assert "update_jira_issue.py" in second_uv.read_text(encoding="utf-8")
