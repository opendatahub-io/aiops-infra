#!/usr/bin/env bash
# Creates the working directory for a skill run.
# Outputs KEY=VALUE lines for eval in the caller. Working directory message goes to stderr.
set -euo pipefail

JIRA_ID=""
YAML_FILENAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-id)       JIRA_ID="$2";       shift 2 ;;
    --yaml-filename) YAML_FILENAME="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -n "$JIRA_ID" ]]; then
  WORKDIR="$(pwd)/${JIRA_ID}"
else
  WORKDIR="$(pwd)"
fi

mkdir -p "$WORKDIR"
echo "Working directory: $WORKDIR" >&2

echo "WORKDIR=${WORKDIR}"
if [[ -n "$YAML_FILENAME" ]]; then
  echo "YAML_PATH=${WORKDIR}/${YAML_FILENAME}"
fi
