#!/usr/bin/env bash
# config.sh — Default configuration values for build-buddy
#
# Source this file to get all default values. Environment variables
# override any default set here.

set -euo pipefail

# ── Pipeline-Pilot container ────────────────────────────────────────────────
export BB_PP_IMAGE="${BB_PP_IMAGE:-quay.io/rhoai-devops/pipeline-pilot:latest}"
export BB_PP_CONTAINER_NAME="${BB_PP_CONTAINER_NAME:-build-buddy-pp}"

# ── Output ──────────────────────────────────────────────────────────────────
export BB_OUTPUT_DIR="${BB_OUTPUT_DIR:-./build-buddy-output}"

# ── Execution mode ──────────────────────────────────────────────────────────
# interactive = ask before Jira updates / retrigger
# ci          = auto-update Jira, auto-retrigger within guardrails
export BB_EXECUTION_MODE="${BB_EXECUTION_MODE:-interactive}"
export BB_DRY_RUN="${BB_DRY_RUN:-false}"
export BB_ALLOW_RETRIGGER="${BB_ALLOW_RETRIGGER:-true}"

# ── Retrigger guardrails ────────────────────────────────────────────────────
export BB_MAX_RETRIGGER_ATTEMPTS="${BB_MAX_RETRIGGER_ATTEMPTS:-2}"

# ── Konflux / PaC domains ──────────────────────────────────────────────────
# Used for URL pattern matching when extracting pipeline URLs from Jira
export BB_KONFLUX_DOMAINS="${BB_KONFLUX_DOMAINS:-konflux.apps.stone-prd-rh01.pg1f.p1.openshiftapps.com,console-openshift-console.apps.stone-prd-rh01.pg1f.p1.openshiftapps.com}"

# ── Intermittent failure signals ────────────────────────────────────────────
# Patterns that strongly indicate an intermittent (infra) failure
export BB_INTERMITTENT_PATTERNS="${BB_INTERMITTENT_PATTERNS:-ImagePullBackOff|ErrImagePull|network timeout|connection reset|i/o timeout|OOMKilled|DeadlineExceeded|context deadline exceeded|TLS handshake timeout|dial tcp.*connect: connection refused|no space left on device}"
