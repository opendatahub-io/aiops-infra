#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "python-gitlab>=3.0.0",
# ]
# ///
"""
Monitor a GitLab merge request until it is merged, closed, or times out.

Supports a --check-only mode that prints the current MR state and exits immediately
(used by create-quay-repo SKILL.md to inspect existing Merge Requests without polling).

Authentication:
  GITLAB_USER   — required; GitLab username
  GITLAB_TOKEN  — required; personal access token with api scope

Usage:
  monitor_gitlab_mr.py \
    --mr-url <url>            # mandatory; full GitLab MR web URL
    [--timeout <minutes>]     # optional; polling timeout in minutes (default: 60)
    [--check-only]            # optional; print state once and exit

Output:

  --check-only mode (stdout):
    state=<opened|merged|closed>
    title=<MR title>

  Polling mode:
    Progress lines are written to stderr every 60 seconds.
    On terminal event, one word is written to stdout:
      merged   → MR was merged
      closed   → MR was closed without merging
      timeout  → timeout reached while MR still open

Exit codes:
  0  merged (or check-only with a valid response)
  1  closed, pipeline failed, or timeout
  2  URL parse error, auth failure, project/MR not found
"""

import argparse
import os
import re
import sys
import time
import warnings

import gitlab
from gitlab.exceptions import GitlabAuthenticationError, GitlabError, GitlabGetError

POLL_INTERVAL_S = 60  # seconds between status checks


def require_env(name: str, hint: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: {name} environment variable is not set.", file=sys.stderr)
        print(f"  {hint}", file=sys.stderr)
        sys.exit(2)
    return value


def parse_mr_url(mr_url: str) -> tuple[str, str, int]:
    """
    Parse a GitLab MR URL and return (base_url, project_path, mr_iid).

    Expected format: https://<host>/<namespace>/<project>/-/merge_requests/<iid>
    """
    pattern = r"^(https?://[^/]+)/(.+)/-/merge_requests/(\d+)"
    match = re.match(pattern, mr_url.rstrip("/"))
    if not match:
        print("ERROR: Cannot parse MR URL.", file=sys.stderr)
        print("  Expected format: https://<host>/<namespace>/<project>/-/merge_requests/<iid>", file=sys.stderr)
        print(f"  Got: {mr_url}", file=sys.stderr)
        sys.exit(2)
    base_url = match.group(1)
    project_path = match.group(2)
    mr_iid = int(match.group(3))
    return base_url, project_path, mr_iid


def _ssl_verify() -> bool:
    val = os.environ.get("GITLAB_SSL_VERIFY", "true").strip().lower()
    skip = val in ("0", "false", "no", "off")
    if skip:
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    return not skip


def get_gitlab_client(base_url: str, token: str) -> gitlab.Gitlab:
    verify = _ssl_verify()
    try:
        gl = gitlab.Gitlab(url=base_url, private_token=token, ssl_verify=verify)
        gl.auth()
        return gl
    except GitlabAuthenticationError:
        print("ERROR: GitLab authentication failed. Check GITLAB_TOKEN.", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        msg = str(exc).lower()
        if "ssl" in msg or "certificate" in msg:
            print(f"ERROR: SSL certificate verification failed for {base_url}.", file=sys.stderr)
            print("  Set GITLAB_SSL_VERIFY=false to skip verification for internal CAs.", file=sys.stderr)
            sys.exit(2)
        if any(k in msg for k in ("connection", "timeout", "name resolution", "no route")):
            print(f"ERROR: Cannot reach {base_url}. Ensure VPN is active.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to connect to GitLab: {exc}", file=sys.stderr)
        sys.exit(2)


def get_project_and_mr(gl: gitlab.Gitlab, project_path: str, mr_iid: int):
    """Fetch the project and MR objects, exiting with code 2 on any lookup error."""
    try:
        project = gl.projects.get(project_path)
    except GitlabGetError as exc:
        if exc.response_code == 404:
            print(f"ERROR: Project not found: {project_path}", file=sys.stderr)
            print("  Check VPN and that the MR URL is correct.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch project {project_path}: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "timeout", "name resolution")):
            print("ERROR: Cannot reach GitLab. Ensure VPN is active.", file=sys.stderr)
        else:
            print(f"ERROR: Unexpected error fetching project: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        mr = project.mergerequests.get(mr_iid)
    except GitlabGetError as exc:
        if exc.response_code == 404:
            print(f"ERROR: MR !{mr_iid} not found in project {project_path}.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to fetch MR !{mr_iid}: {exc}", file=sys.stderr)
        sys.exit(2)

    return project, mr


def print_pipeline_failures(project, pipeline_id: int) -> None:
    """Print failed job names and URLs from a pipeline, for diagnostics."""
    try:
        pipeline = project.pipelines.get(pipeline_id)
        jobs = pipeline.jobs.list(all=True)
        failed = [j for j in jobs if j.status == "failed"]
        if failed:
            print("  Failed pipeline jobs:", file=sys.stderr)
            for job in failed:
                print(f"    - {job.name}: {job.web_url}", file=sys.stderr)
    except GitlabError as exc:
        print(f"  WARNING: Could not fetch pipeline jobs: {exc}", file=sys.stderr)


def check_only_mode(project, mr) -> None:
    """Print MR state info to stdout and exit 0."""
    print(f"state={mr.state}")
    print(f"title={mr.title}")
    sys.exit(0)


def poll_mode(project, mr, mr_iid: int, timeout_minutes: int) -> None:
    """Poll the MR every POLL_INTERVAL_S seconds until terminal state or timeout."""
    deadline = time.time() + timeout_minutes * 60
    iteration = 0

    while time.time() < deadline:
        # Refresh MR state on every iteration (after first immediate check)
        if iteration > 0:
            time.sleep(POLL_INTERVAL_S)
            try:
                mr = project.mergerequests.get(mr_iid)
            except GitlabError as exc:
                print(f"[WARN] Could not refresh MR status: {exc}", file=sys.stderr)
                continue

        iteration += 1
        state = mr.state
        elapsed_min = int((time.time() - (deadline - timeout_minutes * 60)) / 60)

        # ── Terminal states ────────────────────────────────────────────────────
        if state == "merged":
            print(f"[INFO] MR !{mr_iid} merged successfully.", file=sys.stderr)
            print("merged")
            sys.exit(0)

        if state == "closed":
            print(f"[ERROR] MR !{mr_iid} was closed without merging.", file=sys.stderr)
            print("closed")
            sys.exit(1)

        # ── Check pipeline status ──────────────────────────────────────────────
        pipeline = getattr(mr, "pipeline", None)
        pipeline_status = None
        pipeline_id = None

        if pipeline and isinstance(pipeline, dict):
            pipeline_status = pipeline.get("status")
            pipeline_id = pipeline.get("id")
        elif hasattr(pipeline, "status"):
            pipeline_status = pipeline.status
            pipeline_id = getattr(pipeline, "id", None)

        if pipeline_status in ("failed", "canceled"):
            print(f"[ERROR] Pipeline {pipeline_status} on MR !{mr_iid}.", file=sys.stderr)
            if pipeline_id:
                print_pipeline_failures(project, pipeline_id)
            print(f"pipeline_{pipeline_status}")
            sys.exit(1)

        # ── Still open — report progress ───────────────────────────────────────
        pipeline_str = f"pipeline={pipeline_status}" if pipeline_status else "no pipeline"
        remaining_min = max(0, int((deadline - time.time()) / 60))
        print(
            f"[INFO] MR !{mr_iid} still open "
            f"(elapsed={elapsed_min}m, remaining={remaining_min}m, {pipeline_str}). "
            f"Checking again in {POLL_INTERVAL_S}s...",
            file=sys.stderr,
        )

    # ── Timeout ────────────────────────────────────────────────────────────────
    print(f"[ERROR] Timeout: MR !{mr_iid} still open after {timeout_minutes} minutes.", file=sys.stderr)
    print("timeout")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mr-url",
        required=True,
        metavar="URL",
        help="Full GitLab MR web URL (e.g. https://$GITLAB_HOST/namespace/project/-/merge_requests/42)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="MINUTES",
        help="Polling timeout in minutes (default: 60). Ignored in --check-only mode.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Print current MR state and exit immediately without polling.",
    )
    args = parser.parse_args()

    _gitlab_user = require_env("GITLAB_USER", "export GITLAB_USER=yourusername")
    gitlab_token = require_env("GITLAB_TOKEN", "export GITLAB_TOKEN=yourtoken")

    base_url, project_path, mr_iid = parse_mr_url(args.mr_url)

    print(f"Connecting to {base_url}...", file=sys.stderr)
    gl = get_gitlab_client(base_url, gitlab_token)

    print(f"Fetching MR !{mr_iid} from {project_path}...", file=sys.stderr)
    project, mr = get_project_and_mr(gl, project_path, mr_iid)

    print(f"  Title: {mr.title}", file=sys.stderr)
    print(f"  State: {mr.state}", file=sys.stderr)

    if args.check_only:
        check_only_mode(project, mr)
    else:
        print(f"  Polling every {POLL_INTERVAL_S}s, timeout={args.timeout}m.", file=sys.stderr)
        poll_mode(project, mr, mr_iid, args.timeout)


if __name__ == "__main__":
    main()
