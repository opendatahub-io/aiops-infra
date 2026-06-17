"""cli_runner.py -- Generic subprocess wrapper + CLI tool runners (dual-mode: CLI + importable).

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

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Mapping, Sequence

# ---------------------------------------------------------------------------
# Generic subprocess helpers
# ---------------------------------------------------------------------------


def run(
    cmd: Sequence[str],
    timeout: int = 60,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Run command. Returns {"returncode": int, "stdout": str, "stderr": str, "timed_out": bool}."""
    if not cmd:
        return {"returncode": 1, "stdout": "", "stderr": "empty command", "timed_out": False}
    try:
        completed = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": -1,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
        }
    except FileNotFoundError as exc:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }


def run_with_retry(
    cmd: Sequence[str],
    max_retries: int = 3,
    delay: int = 2,
    timeout: int = 60,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Run command with retries on failure."""
    attempts = 0
    last_result = {
        "returncode": -1,
        "stdout": "",
        "stderr": "",
        "timed_out": False,
    }

    for attempt in range(1, max_retries + 1):
        attempts = attempt
        last_result = run(cmd, timeout=timeout, cwd=cwd, env=env)
        if last_result["returncode"] == 0 and not last_result["timed_out"]:
            break
        if attempt < max_retries:
            time.sleep(delay)

    return {
        "returncode": last_result["returncode"],
        "stdout": last_result["stdout"],
        "stderr": last_result["stderr"],
        "attempts": attempts,
    }


def run_json(cmd: Sequence[str], timeout: int = 60, cwd: str | None = None) -> dict:
    """Run command expecting JSON stdout."""
    result = run(cmd, timeout=timeout, cwd=cwd)
    if result["timed_out"]:
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": "Command timed out",
        }
    if result["returncode"] != 0:
        error = result["stderr"].strip() or f"Command failed with exit code {result['returncode']}"
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": error,
        }

    stdout = result["stdout"].strip()
    if not stdout:
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": "Command produced no stdout",
        }

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": f"Invalid JSON output: {exc}",
        }

    if not isinstance(data, dict):
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": f"Expected JSON object, got {type(data).__name__}",
        }

    return {
        "returncode": result["returncode"],
        "data": data,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Token / env-var resolution
# ---------------------------------------------------------------------------

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

_CONFORMA_CONFIG_DIR = Path.home() / ".config" / "conforma-exception"
_OLD_CONFORMA_CONFIG_DIR = Path.home() / ".config" / "conforma-exception-create"

_TOKEN_FILES: dict[str, Path] = {
    "GITLAB_TOKEN": Path.home() / ".config" / "glab-cli" / "token",
    "JIRA_API_TOKEN": _CONFORMA_CONFIG_DIR / "jira_api_token",
    "JIRA_EMAIL": _CONFORMA_CONFIG_DIR / "jira_email",
}


def _migrate_old_config_dir() -> None:
    """One-time migration: copy token files from old config dir to new one."""
    if not _OLD_CONFORMA_CONFIG_DIR.is_dir():
        return
    if _CONFORMA_CONFIG_DIR.is_dir() and any(_CONFORMA_CONFIG_DIR.iterdir()):
        return
    _CONFORMA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for src in _OLD_CONFORMA_CONFIG_DIR.iterdir():
        if src.is_file():
            dst = _CONFORMA_CONFIG_DIR / src.name
            if not dst.exists():
                dst.write_bytes(src.read_bytes())
                dst.chmod(src.stat().st_mode)


def _get_email_from_acli_config() -> str | None:
    """Extract email from acli's stored config (jira_config.yaml)."""
    try:
        import yaml
    except ImportError:
        return None
    for config_dir in _ACLI_CONFIG_CANDIDATES:
        jira_config = config_dir / "jira_config.yaml"
        if jira_config.is_file():
            try:
                with open(jira_config) as f:
                    config = yaml.safe_load(f)
                for p in config.get("profiles", []):
                    if "email" in p:
                        return p["email"]
            except Exception:
                continue
    return None


def _resolve_env(var: str) -> str | None:
    """Return the value of an env var, falling back to saved token files.

    Resolution order:
      1. Environment variable
      2. Token file in ~/.config/conforma-exception/
      3. For JIRA_EMAIL: acli config -> $USER@redhat.com fallback
    """
    _migrate_old_config_dir()

    val = os.environ.get(var)
    if val:
        return val
    token_file = _TOKEN_FILES.get(var)
    if token_file and token_file.is_file():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    if var == "JIRA_EMAIL":
        acli_email = _get_email_from_acli_config()
        if acli_email:
            return acli_email
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


# ---------------------------------------------------------------------------
# CLI binary discovery
# ---------------------------------------------------------------------------


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
            f'Note: {_ACLI_LOCAL_BIN.parent} is not on PATH. Add it with: export PATH="$HOME/.local/bin:$PATH"',
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


# ---------------------------------------------------------------------------
# CLI runners (acli + glab)
# ---------------------------------------------------------------------------


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
            "'acli' not found on PATH, auto-install failed, and no container runtime (docker/podman) is available."
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


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generic subprocess wrapper")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run")
    run_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command after --")

    run_json_parser = sub.add_parser("run-json")
    run_json_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command after --")

    args = parser.parse_args()

    if args.command in {"run", "run-json"}:
        cmd = list(args.cmd)
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        if not cmd:
            parser.error("a command is required after --")

        if args.command == "run":
            result = run(cmd)
        else:
            result = run_json(cmd)
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
