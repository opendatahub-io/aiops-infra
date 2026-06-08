#!/usr/bin/env python3
"""CLI runner with native-first, container-fallback execution for acli and glab.

Resolution order for acli:
  1. Native binary on PATH (fastest, preferred)
  2. Binary in ~/.local/bin (auto-installed from Atlassian CDN)
  3. Container via docker or podman (last resort)

Resolution order for glab:
  1. Native binary on PATH
  2. Container via docker or podman (automatic fallback)

Container images are configurable via environment variables:
  - ACLI_IMAGE  (default: docker.io/davidsmith3/acli:latest)
  - GLAB_IMAGE  (default: docker.io/gitlab/glab:latest)
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

_DEFAULT_ACLI_IMAGE = "docker.io/davidsmith3/acli:latest"
_DEFAULT_GLAB_IMAGE = "docker.io/gitlab/glab:latest"

_ACLI_CDN_BASE = "https://acli.atlassian.com"
_ACLI_LOCAL_BIN = Path.home() / ".local" / "bin" / "acli"

_ACLI_FILE_FLAGS = frozenset({"--from-json", "--body-file"})

_ACLI_CONFIG_CANDIDATES = [
    Path.home() / ".acli",
    Path.home() / ".config" / "acli",
]
_GLAB_CONFIG_CANDIDATES = [
    Path.home() / ".config" / "glab-cli",
]

_ACLI_ENV_VARS: tuple[str, ...] = ()
_GLAB_ENV_VARS = ("GITLAB_TOKEN", "GITLAB_HOST", "GL_HOST")

_CONFORMA_CONFIG_DIR = Path.home() / ".config" / "conforma-exception-create"

_TOKEN_FILES: dict[str, Path] = {
    "GITLAB_TOKEN": Path.home() / ".config" / "glab-cli" / "token",
    "JIRA_API_TOKEN": _CONFORMA_CONFIG_DIR / "jira_api_token",
    "JIRA_EMAIL": _CONFORMA_CONFIG_DIR / "jira_email",
}


def _resolve_env(var: str) -> str | None:
    """Return the value of an env var, falling back to a saved token file.

    For JIRA_EMAIL, also falls back to $USER@redhat.com if not explicitly set.
    """
    val = os.environ.get(var)
    if val:
        return val
    token_file = _TOKEN_FILES.get(var)
    if token_file and token_file.is_file():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    if var == "JIRA_EMAIL":
        import getpass

        return f"{getpass.getuser()}@redhat.com"
    return None


def save_token(var: str, value: str) -> Path:
    """Save a token to its config file (0600 permissions). Returns the path."""
    token_file = _TOKEN_FILES[var]
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(value + "\n", encoding="utf-8")
    token_file.chmod(0o600)
    return token_file


def _acli_platform_slug() -> str:
    """Return the Atlassian CDN path segment for the current platform."""
    os_name = platform.system().lower()
    machine = platform.machine().lower()
    arch_map = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    arch = arch_map.get(machine)
    if not arch or os_name not in ("linux", "darwin"):
        raise RuntimeError(f"Unsupported platform: {os_name}/{machine}")
    return f"{os_name}/latest/acli_{os_name}_{arch}/acli"


def _find_acli() -> str | None:
    """Find acli binary: PATH first, then ~/.local/bin."""
    found = shutil.which("acli")
    if found:
        return found
    if _ACLI_LOCAL_BIN.is_file() and os.access(_ACLI_LOCAL_BIN, os.X_OK):
        return str(_ACLI_LOCAL_BIN)
    return None


def _install_acli_local() -> str:
    """Download acli from the Atlassian CDN to ~/.local/bin/acli.

    Raises RuntimeError on unsupported platform or download failure.
    """
    slug = _acli_platform_slug()
    url = f"{_ACLI_CDN_BASE}/{slug}"
    _ACLI_LOCAL_BIN.parent.mkdir(parents=True, exist_ok=True)

    print(f"Installing acli to {_ACLI_LOCAL_BIN} ...", file=sys.stderr)
    try:
        urllib.request.urlretrieve(url, _ACLI_LOCAL_BIN)  # noqa: S310
    except Exception as exc:
        _ACLI_LOCAL_BIN.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download acli from {url}: {exc}") from exc

    _ACLI_LOCAL_BIN.chmod(0o755)

    if str(_ACLI_LOCAL_BIN.parent) not in os.environ.get("PATH", ""):
        print(
            f"Note: {_ACLI_LOCAL_BIN.parent} is not on PATH. "
            f'Add it with: export PATH="$HOME/.local/bin:$PATH"',
            file=sys.stderr,
        )

    print(f"acli installed successfully: {_ACLI_LOCAL_BIN}", file=sys.stderr)
    return str(_ACLI_LOCAL_BIN)


def _container_runtime() -> str | None:
    """Return the first available container runtime ('docker' or 'podman')."""
    for rt in ("docker", "podman"):
        if shutil.which(rt):
            return rt
    return None


def _find_or_create_config_dir(candidates: list[Path]) -> Path | None:
    """Find the first existing config dir, or create the last candidate."""
    for d in candidates:
        if d.is_dir():
            return d
    preferred = candidates[-1]
    preferred.mkdir(parents=True, exist_ok=True)
    return preferred


def _rewrite_file_flags(
    args: list[str],
    file_flags: frozenset[str],
    volumes: list[str],
) -> list[str]:
    """Detect file-path flags, add volume mounts, and rewrite paths."""
    rewritten = list(args)
    mount_idx = 0
    i = 0
    while i < len(rewritten):
        if rewritten[i] in file_flags and i + 1 < len(rewritten):
            host_path = Path(rewritten[i + 1])
            if host_path.exists():
                container_path = f"/mnt/input_{mount_idx}"
                volumes.append(f"{host_path.resolve()}:{container_path}:ro")
                rewritten[i + 1] = container_path
                mount_idx += 1
        i += 1
    return rewritten


def _build_container_cmd(
    runtime: str,
    image: str,
    cli_cmd: list[str],
    config_candidates: list[Path],
    container_config_path: str,
    env_var_names: tuple[str, ...],
    file_flags: frozenset[str],
    cwd: Path | str | None = None,
) -> list[str]:
    """Build a 'docker/podman run' command with mounts and env forwarding."""
    cmd = [runtime, "run", "--rm", "--network", "host", "--entrypoint", ""]

    config_dir = _find_or_create_config_dir(config_candidates)
    if config_dir:
        cmd.extend(["-v", f"{config_dir}:{container_config_path}:ro"])

    for var in env_var_names:
        val = _resolve_env(var)
        if val:
            cmd.extend(["-e", f"{var}={val}"])

    if cwd:
        abs_cwd = str(Path(cwd).resolve())
        cmd.extend(["-v", f"{abs_cwd}:/workspace", "-w", "/workspace"])

    volumes: list[str] = []
    rewritten_cmd = _rewrite_file_flags(cli_cmd, file_flags, volumes)
    for vol in volumes:
        cmd.extend(["-v", vol])

    cmd.append(image)
    cmd.extend(rewritten_cmd)
    return cmd


def run_acli(
    args: list[str],
    *,
    capture_output: bool = True,
    text: bool = True,
    timeout: int = 30,
    cwd: Path | str | None = None,
) -> subprocess.CompletedProcess:
    """Run an acli command: PATH -> ~/.local/bin -> auto-install -> container."""
    acli_bin = _find_acli()

    if not acli_bin:
        try:
            acli_bin = _install_acli_local()
        except (RuntimeError, OSError):
            acli_bin = None

    if acli_bin:
        return subprocess.run(
            [acli_bin, *args],
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            cwd=cwd,
        )

    runtime = _container_runtime()
    if not runtime:
        raise FileNotFoundError(
            "'acli' not found on PATH, auto-install failed, and no container "
            "runtime (docker/podman) is available."
        )

    image = os.environ.get("ACLI_IMAGE", _DEFAULT_ACLI_IMAGE)
    container_cmd = _build_container_cmd(
        runtime=runtime,
        image=image,
        cli_cmd=["acli", *args],
        config_candidates=_ACLI_CONFIG_CANDIDATES,
        container_config_path="/root/.config/acli",
        env_var_names=_ACLI_ENV_VARS,
        file_flags=_ACLI_FILE_FLAGS,
        cwd=cwd,
    )
    return subprocess.run(
        container_cmd,
        capture_output=capture_output,
        text=text,
        timeout=timeout + 30,
    )


def run_glab(
    args: list[str],
    *,
    capture_output: bool = True,
    text: bool = True,
    timeout: int = 30,
    cwd: Path | str | None = None,
) -> subprocess.CompletedProcess:
    """Run a glab command natively or via container fallback."""
    if shutil.which("glab"):
        return subprocess.run(
            ["glab", *args],
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            cwd=cwd,
        )

    runtime = _container_runtime()
    if not runtime:
        raise FileNotFoundError(
            "'glab' not found on PATH and no container runtime (docker/podman) "
            "is available. Install glab or a container runtime."
        )

    image = os.environ.get("GLAB_IMAGE", _DEFAULT_GLAB_IMAGE)
    container_cmd = _build_container_cmd(
        runtime=runtime,
        image=image,
        cli_cmd=["glab", *args],
        config_candidates=_GLAB_CONFIG_CANDIDATES,
        container_config_path="/root/.config/glab-cli",
        env_var_names=_GLAB_ENV_VARS,
        file_flags=frozenset(),
        cwd=cwd,
    )
    return subprocess.run(
        container_cmd,
        capture_output=capture_output,
        text=text,
        timeout=timeout + 30,
    )


def resolve_method(binary: str) -> str:
    """Return how a binary would be executed: 'native', 'docker', 'podman', or 'unavailable'."""
    if binary == "acli" and _find_acli():
        return "native"
    if shutil.which(binary):
        return "native"
    rt = _container_runtime()
    return rt if rt else "unavailable"
