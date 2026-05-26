"""GitLab API: create merge requests via python-gitlab."""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import gitlab
from gitlab.exceptions import GitlabCreateError

from constants import GITLAB_API_URL, GITLAB_PROJECT_PATH, REPO_BRANCH

logger = logging.getLogger(__name__)


def _gitlab_api_token() -> Optional[str]:
    """
    Token for GitLab REST API (merge requests).

    MR creation requires **api** scope. Git push over HTTPS may work with only
    read_repository + write_repository, which yields ``403 insufficient_scope`` on the API.

    Prefer ``KONFLUX_MR_TOKEN`` when your push token is intentionally narrow; otherwise
    ``KONFLUX_REPO_TOKEN`` must include **api**.
    """
    return os.environ.get("KONFLUX_MR_TOKEN") or os.environ.get("KONFLUX_REPO_TOKEN")


@dataclass(frozen=True)
class MergeRequestInfo:
    """Created (or existing) merge request identifiers for CI and logging."""

    web_url: str
    reference: str
    iid: int


def _mr_to_info(mr) -> MergeRequestInfo:
    refs = getattr(mr, "references", None) or mr.attributes.get("references") or {}
    full_ref = refs.get("full") if isinstance(refs, dict) else None
    if not full_ref:
        full_ref = f"{GITLAB_PROJECT_PATH}!{mr.iid}"
    return MergeRequestInfo(web_url=mr.web_url, reference=full_ref, iid=mr.iid)


def create_merge_request(
    source_branch: str,
    title: str,
    target_branch: str = REPO_BRANCH,
) -> Optional[MergeRequestInfo]:
    """
    Create an MR using project.mergerequests.create().

    Uses KONFLUX_REPO_TOKEN (same as git push). Token needs ``api`` scope to create MRs
    (``write_repository`` alone is not enough for the REST API).

    Returns MergeRequestInfo, or None if no token is set.

    If an open MR already exists for the branch, returns that MR instead of failing.

    Set GITLAB_SSL_VERIFY=false in environments with an internal CA not trusted by default.
    """
    token = _gitlab_api_token()
    if not token:
        logger.info(
            "No GitLab API token: set KONFLUX_REPO_TOKEN (with api scope) or KONFLUX_MR_TOKEN; skipping MR API"
        )
        return None

    ssl_verify = os.environ.get("GITLAB_SSL_VERIFY", "true").lower() not in (
        "0",
        "false",
        "no",
    )
    if os.environ.get("KONFLUX_MR_TOKEN"):
        logger.info("Using KONFLUX_MR_TOKEN for GitLab REST API (merge requests)")
    gl = gitlab.Gitlab(GITLAB_API_URL, private_token=token, ssl_verify=ssl_verify)
    project = gl.projects.get(GITLAB_PROJECT_PATH)
    try:
        mr = project.mergerequests.create(
            {
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
            }
        )
    except GitlabCreateError as e:
        err = (getattr(e, "error_message", None) or str(e)).lower()
        if "already exists" in err or getattr(e, "response_code", None) == 409:
            opened = project.mergerequests.list(source_branch=source_branch, state="opened")
            if opened:
                info = _mr_to_info(opened[0])
                logger.info("Using existing open merge request: %s", info.web_url)
                return info
        raise
    info = _mr_to_info(mr)
    logger.info("Created merge request: %s (%s)", info.web_url, info.reference)
    return info


def create_merge_request_safe(
    source_branch: str,
    title: str,
    target_branch: str = REPO_BRANCH,
) -> Optional[MergeRequestInfo]:
    """
    Like create_merge_request but catches API errors and returns None so the caller can fall back.
    """
    try:
        return create_merge_request(source_branch, title, target_branch=target_branch)
    except gitlab.GitlabError as e:
        err_s = str(e).lower()
        if "insufficient_scope" in err_s or (
            getattr(e, "response_code", None) == 403 and "scope" in err_s
        ):
            logger.error(
                "GitLab returned 403 insufficient_scope: the token used for the REST API does not "
                "include the **api** scope. Options: (1) Create a new PAT with **api** enabled and set "
                "KONFLUX_REPO_TOKEN, or (2) keep your current push token and set **KONFLUX_MR_TOKEN** "
                "to a separate PAT that has **api** (read_repository + write_repository alone are not enough "
                "for mergerequests.create)."
            )
        else:
            logger.warning("GitLab MR API failed: %s", e)
        return None
