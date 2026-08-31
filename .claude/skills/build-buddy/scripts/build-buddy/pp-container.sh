#!/usr/bin/env bash
# pp-container.sh — Pipeline-Pilot container lifecycle management
#
# Provides functions to start, exec into, and stop the PP container.
# The container is started once per session and reused for all commands.
#
# Usage:
#   source pp-container.sh
#   pp_start                  # Start the PP container
#   pp_exec analyze <args>    # Run a command inside the container
#   pp_stop                   # Stop and remove the container
#   pp_is_running             # Check if container is running (exit 0/1)

set -euo pipefail

# Source config defaults if not already loaded
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
[[ -z "${BB_PP_IMAGE:-}" ]] && source "${SCRIPT_DIR}/config.sh"

# Resolve container runtime
BB_CONTAINER_RUNTIME="${BB_CONTAINER_RUNTIME:-$(command -v podman 2>/dev/null && echo podman || echo docker)}"
if [[ "$BB_CONTAINER_RUNTIME" == *podman* ]]; then
  BB_CONTAINER_RUNTIME="podman"
elif [[ "$BB_CONTAINER_RUNTIME" == *docker* ]]; then
  BB_CONTAINER_RUNTIME="docker"
fi

# ── pp_is_running ───────────────────────────────────────────────────────────
# Check if the PP container is currently running
# Returns: 0 if running, 1 otherwise
pp_is_running() {
  $BB_CONTAINER_RUNTIME inspect --format '{{.State.Running}}' \
    "$BB_PP_CONTAINER_NAME" 2>/dev/null | grep -q "true"
}

# ── pp_start ────────────────────────────────────────────────────────────────
# Start the Pipeline-Pilot container in daemon mode.
# Passes through OC_TOKEN and optional env vars.
# Idempotent — returns 0 if already running.
pp_start() {
  if pp_is_running; then
    echo "PP container '$BB_PP_CONTAINER_NAME' is already running."
    return 0
  fi

  # Remove any stopped container with the same name
  $BB_CONTAINER_RUNTIME rm -f "$BB_PP_CONTAINER_NAME" 2>/dev/null || true

  echo "Starting Pipeline-Pilot container..."
  echo "  Image: $BB_PP_IMAGE"
  echo "  Name:  $BB_PP_CONTAINER_NAME"

  local env_args=()
  env_args+=(-e "OC_TOKEN=${OC_TOKEN:-}")
  [[ -n "${KUBEARCHIVE_URL:-}" ]]                && env_args+=(-e "KUBEARCHIVE_URL=${KUBEARCHIVE_URL}")
  [[ -n "${VERTEX_PROJECT_ID:-}" ]]              && env_args+=(-e "VERTEX_PROJECT_ID=${VERTEX_PROJECT_ID}")
  [[ -n "${VERTEX_LOCATION:-}" ]]                && env_args+=(-e "VERTEX_LOCATION=${VERTEX_LOCATION}")
  [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]] && env_args+=(-e "GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS}")

  $BB_CONTAINER_RUNTIME run -d \
    --name "$BB_PP_CONTAINER_NAME" \
    "${env_args[@]}" \
    "$BB_PP_IMAGE" \
    sleep infinity

  # Verify it started
  if pp_is_running; then
    echo "PP container started successfully."
    return 0
  else
    echo "ERROR: PP container failed to start." >&2
    $BB_CONTAINER_RUNTIME logs "$BB_PP_CONTAINER_NAME" 2>&1 || true
    return 1
  fi
}

# ── pp_exec ─────────────────────────────────────────────────────────────────
# Execute a command inside the running PP container.
# Usage: pp_exec <command> [args...]
# Returns: exit code from the container command
pp_exec() {
  if ! pp_is_running; then
    echo "ERROR: PP container '$BB_PP_CONTAINER_NAME' is not running." >&2
    echo "  Call pp_start first." >&2
    return 1
  fi

  $BB_CONTAINER_RUNTIME exec "$BB_PP_CONTAINER_NAME" "$@"
}

# ── pp_stop ─────────────────────────────────────────────────────────────────
# Stop and remove the PP container. Idempotent.
pp_stop() {
  if pp_is_running; then
    echo "Stopping PP container '$BB_PP_CONTAINER_NAME'..."
    $BB_CONTAINER_RUNTIME stop "$BB_PP_CONTAINER_NAME" 2>/dev/null || true
  fi
  $BB_CONTAINER_RUNTIME rm -f "$BB_PP_CONTAINER_NAME" 2>/dev/null || true
  echo "PP container cleaned up."
}

# ── pp_analyze ──────────────────────────────────────────────────────────────
# Run Pipeline-Pilot analyze command for a PipelineRun URL.
# Usage: pp_analyze <pipelinerun-url> [--output-file <path>]
# Captures JSON output to stdout.
pp_analyze() {
  local pr_url="$1"
  shift
  local output_file=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --output-file) output_file="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  local result
  result=$(pp_exec pipeline-pilot analyze "$pr_url" 2>&1) || {
    echo "ERROR: Pipeline-Pilot analyze failed." >&2
    echo "$result" >&2
    return 1
  }

  if [[ -n "$output_file" ]]; then
    echo "$result" > "$output_file"
  fi

  echo "$result"
}
