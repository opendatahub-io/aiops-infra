#!/usr/bin/env python3
"""Validate all links in a Conforma Resolution Guide.

Checks both internal anchor references and external HTTP(S) URLs.
Auth tokens are applied automatically for GitHub and GitLab URLs.

Usage:
    # Validate a specific guide file:
    python3 skills/conforma-analyze/scripts/validate_guide_links.py \
      --guide-file ~/.conforma/20260610-143449/conforma-status-and-resolution-guide.md

    # Auto-find the most recent guide in ~/.conforma/:
    python3 skills/conforma-analyze/scripts/validate_guide_links.py --latest
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse

import conforma_context_ops  # noqa: E402
import requests

LINK_CHECK_TIMEOUT = 15
LINK_CHECK_MAX_WORKERS = 10

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")
_HTML_HREF_RE = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>([^<]*)</a>', re.IGNORECASE)
_HTML_ANCHOR_ID_RE = re.compile(r'<a\s+id="([^"]+)"', re.IGNORECASE)
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


class LinkCheckResult(NamedTuple):
    url: str
    ok: bool
    status_code: int | None
    reason: str


def _get_github_token() -> str:
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def _get_gitlab_token() -> str:
    token = os.environ.get("GITLAB_TOKEN", "").strip()
    if token:
        return token
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
        import gitlab_ops
        return gitlab_ops.discover_token() or ""
    except Exception:
        return ""


def extract_markdown_links(content: str) -> list[tuple[str, str]]:
    """Extract (label, url) pairs from markdown and HTML link syntax.

    Handles both ``[label](url)`` and ``<a href="url">label</a>``.
    Returns deduplicated list preserving first-seen order.
    """
    seen: set[str] = set()
    links: list[tuple[str, str]] = []

    for label, url in _MARKDOWN_LINK_RE.findall(content):
        url = url.strip()
        if url not in seen:
            seen.add(url)
            links.append((label, url))

    for url, label in _HTML_HREF_RE.findall(content):
        url = url.strip()
        if url not in seen:
            seen.add(url)
            links.append((label, url))

    return links


def _collect_document_anchors(content: str) -> set[str]:
    """Collect all valid anchor targets from the guide.

    Includes explicit ``<a id="...">`` tags and auto-generated heading anchors
    (GitHub-style: lowercase, spaces to hyphens, strip non-alphanumeric).
    """
    anchors: set[str] = set()

    for match in _HTML_ANCHOR_ID_RE.finditer(content):
        anchors.add(match.group(1))

    for match in _MD_HEADING_RE.finditer(content):
        heading = match.group(1).strip()
        heading = re.sub(r"<[^>]+>", "", heading)
        heading = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
        heading = re.sub(r"[`*_~]", "", heading)
        slug = heading.lower().replace(" ", "-")
        slug = re.sub(r"[^a-z0-9_-]", "", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        anchors.add(slug)

    return anchors


def _auth_headers_for_url(url: str) -> dict[str, str]:
    """Return auth headers appropriate for the URL's host."""
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if host == "github.com" or host.endswith(".github.com"):
        token = _get_github_token()
        if token:
            return {"Authorization": f"token {token}"}
    elif "gitlab" in host or host.endswith(".redhat.com"):
        token = _get_gitlab_token()
        if token:
            return {"PRIVATE-TOKEN": token}

    return {}


def _check_single_link(url: str) -> LinkCheckResult:
    """Validate a single external URL with a HEAD request (GET fallback)."""
    headers = _auth_headers_for_url(url)
    headers["User-Agent"] = "conforma-status-and-resolution-guide-link-checker/1.0"

    for method in (requests.head, requests.get):
        try:
            resp = method(url, headers=headers, timeout=LINK_CHECK_TIMEOUT, allow_redirects=True)
            if resp.status_code < 400:
                return LinkCheckResult(url=url, ok=True, status_code=resp.status_code, reason="OK")
            if method is requests.head and resp.status_code == 405:
                continue
            return LinkCheckResult(
                url=url, ok=False, status_code=resp.status_code,
                reason=f"HTTP {resp.status_code}",
            )
        except requests.ConnectionError:
            return LinkCheckResult(url=url, ok=False, status_code=None, reason="Connection failed")
        except requests.Timeout:
            return LinkCheckResult(url=url, ok=False, status_code=None, reason="Timeout")
        except requests.RequestException as exc:
            return LinkCheckResult(url=url, ok=False, status_code=None, reason=str(exc))

    return LinkCheckResult(url=url, ok=False, status_code=None, reason="All request methods failed")


def validate_guide_links(
    content: str,
    max_workers: int = LINK_CHECK_MAX_WORKERS,
) -> dict:
    """Validate all links in the resolution guide markdown.

    Returns a dict with:
      - total: total unique links found
      - external_checked: number of external URLs checked
      - anchor_checked: number of internal anchors checked
      - broken: list of LinkCheckResult dicts for broken links
      - all_ok: bool
    """
    links = extract_markdown_links(content)
    anchors = _collect_document_anchors(content)

    external_urls: list[str] = []
    anchor_refs: list[tuple[str, str]] = []

    for label, url in links:
        if url.startswith("#"):
            anchor_refs.append((label, url[1:]))
        elif url.startswith("http://") or url.startswith("https://"):
            external_urls.append(url)

    broken: list[dict] = []

    for label, anchor_id in anchor_refs:
        if anchor_id not in anchors:
            broken.append({
                "url": f"#{anchor_id}",
                "ok": False,
                "status_code": None,
                "reason": "Anchor target not found in document",
            })

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check_single_link, url): url for url in external_urls}
        for future in as_completed(futures):
            result = future.result()
            if not result.ok:
                broken.append(result._asdict())

    return {
        "total": len(links),
        "external_checked": len(external_urls),
        "anchor_checked": len(anchor_refs),
        "broken": broken,
        "all_ok": len(broken) == 0,
    }


def find_latest_guide(work_dir: str = str(Path.home() / ".conforma")) -> str | None:
    """Find the most recently modified resolution guide in the work directory."""
    pattern = os.path.join(work_dir, "*", "conforma-status-and-resolution-guide.md")
    candidates = glob.glob(pattern)
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate links in a Conforma Resolution Guide")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Conforma run directory (auto-discovered from ~/.conforma/.conforma-active if omitted)",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--guide-file", help="Path to the resolution guide markdown")
    group.add_argument("--latest", action="store_true", help="Auto-find the most recent guide")
    parser.add_argument("--work-dir", default=None, help="Work directory to search (with --latest)")
    args = parser.parse_args()

    context = None
    run_dir = None
    try:
        run_dir = conforma_context_ops.discover_run_dir(args.run_dir)
        context = conforma_context_ops.load(run_dir)
    except FileNotFoundError:
        if args.run_dir:
            raise

    if args.latest:
        work_dir = args.work_dir
        if work_dir is None and context:
            work_dir = str(conforma_context_ops.discover_work_dir())
        elif work_dir is None:
            work_dir = str(Path.home() / ".conforma")
        guide_file = find_latest_guide(work_dir)
        if not guide_file:
            print(json.dumps({"error": f"No resolution guide found in {work_dir}/", "all_ok": True}))
            return 0
    elif args.guide_file:
        guide_file = args.guide_file
    elif context:
        ctx_guide = conforma_context_ops.get(run_dir, "steps.resolution_guide.guide_file", None)
        if ctx_guide:
            guide_file = str(Path(run_dir) / ctx_guide)
        else:
            print(json.dumps({"error": "No guide_file in context (steps.resolution_guide.guide_file)", "all_ok": False}))
            return 1
    else:
        print(json.dumps({"error": "--guide-file or --latest is required when no run context is available", "all_ok": False}))
        return 1

    path = Path(guide_file)
    if not path.exists():
        print(json.dumps({"error": f"Guide file not found: {guide_file}", "all_ok": False}))
        return 1

    content = path.read_text(encoding="utf-8")
    report = validate_guide_links(content)
    report["guide_file"] = str(path)

    print(json.dumps(report, indent=2))

    if not report["all_ok"]:
        print(f"\nBroken links ({len(report['broken'])}):", file=sys.stderr)
        for entry in report["broken"]:
            print(f"  {entry['url']}  — {entry['reason']}", file=sys.stderr)
        return 1

    print(
        f"All links OK ({report['external_checked']} external, "
        f"{report['anchor_checked']} anchors checked)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
