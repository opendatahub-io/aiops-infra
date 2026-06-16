"""git_ops.py -- Git repository primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess


_SSH_PATTERN = re.compile(r"^[\w.-]+@([\w.-]+):(.*?)(?:\.git)?$")
_HTTPS_PATTERN = re.compile(r"^https?://([\w.-]+)/(.*?)(?:\.git)?$")

_KNOWN_GITHUB_HOSTS = frozenset({"github.com"})


def parse_url(url: str) -> dict:
    """Parse a git remote URL (SSH or HTTPS) into components.

    Returns {"host": str, "repo_path": str, "scheme": "ssh"|"https"}
    or {"error": str}.
    """
    url = url.strip()
    if not url:
        return {"error": "Empty URL"}

    m = _SSH_PATTERN.match(url)
    if m:
        return {"host": m.group(1), "repo_path": m.group(2), "scheme": "ssh"}

    m = _HTTPS_PATTERN.match(url)
    if m:
        return {"host": m.group(1), "repo_path": m.group(2).strip("/"), "scheme": "https"}

    return {"error": f"Unrecognised git URL format: {url}"}


def _classify_platform(host: str) -> str:
    """Classify a hostname as github, gitlab, or unknown."""
    if host in _KNOWN_GITHUB_HOSTS:
        return "github"

    gitlab_host = os.environ.get("GITLAB_HOST") or os.environ.get("GL_HOST") or ""
    if gitlab_host and host == gitlab_host:
        return "gitlab"

    if "gitlab" in host.lower():
        return "gitlab"

    return "unknown"


def detect_remote(cwd: str | None = None, remote: str = "origin") -> dict:
    """Detect the hosting platform from a git remote.

    Returns {"platform": "github"|"gitlab"|"unknown",
             "host": str, "repo_path": str, "url": str}
    or {"error": str}.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            detail = (result.stderr + result.stdout).strip()
            return {"error": detail or f"git remote get-url {remote} failed"}
    except FileNotFoundError:
        return {"error": "git not found on PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "git command timed out"}

    raw_url = result.stdout.strip()
    if not raw_url:
        return {"error": f"Remote '{remote}' returned an empty URL"}

    parsed = parse_url(raw_url)
    if "error" in parsed:
        return parsed

    host = parsed["host"]
    platform = _classify_platform(host)

    https_url = f"https://{host}/{parsed['repo_path']}"

    return {
        "platform": platform,
        "host": host,
        "repo_path": parsed["repo_path"],
        "url": https_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Git repository primitives")
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect-remote")
    p_detect.add_argument("--remote", default="origin")
    p_detect.add_argument("--cwd", default=None)

    p_parse = sub.add_parser("parse-url")
    p_parse.add_argument("--url", required=True)

    args = parser.parse_args()

    if args.command == "detect-remote":
        result = detect_remote(cwd=args.cwd, remote=args.remote)
    elif args.command == "parse-url":
        result = parse_url(args.url)
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
