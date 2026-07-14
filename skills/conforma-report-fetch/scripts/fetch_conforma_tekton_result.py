#!/usr/bin/env python3
"""Fetch a Conforma Tekton report from Konflux via the Tekton Results API.

Resolves a version shortcode or exact PipelineRun name to the newest matching
multi-component Conforma PipelineRun, extracts the EC verification report JSON
from the verify task logs, and writes a handover state document.

Supports three policy types (--type): registry (default), chart, fbc.

Configuration is resolved in order: CLI arg > context.yaml > env var > default.

Usage:
    python3 fetch_conforma_tekton_result.py 3.5 --output /tmp/handover.json
    python3 fetch_conforma_tekton_result.py 3.5ea.2 --type fbc
    python3 fetch_conforma_tekton_result.py conforma-registry-rhoai-prod-v3-5-abcde
    python3 fetch_conforma_tekton_result.py --output /tmp/handover.json  # version from context.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import _setup_env  # noqa: F401

import conforma_context_ops
import requests

STEP_NAME = "step-detailed-report"
TEKTON_RESULTS_API_VERSION = "v1alpha2"

POLICY_TYPES = ("registry", "chart", "fbc")

_DEFAULTS = {
    "namespace": "rhoai-tenant",
    "cluster_domain": None,
    "environment": "prod",
    "app_name": "rhoai",
}


# ---------------------------------------------------------------------------
# Configuration resolution
# ---------------------------------------------------------------------------


def _resolve(
    cli_val: Any,
    context: dict | None,
    context_key: str,
    env_var: str | None = None,
    default: Any = None,
) -> Any:
    if cli_val is not None:
        return cli_val
    if context is not None:
        node: Any = context
        for key in context_key.split("."):
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if node is not None:
            return node
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    return default


def _load_context() -> tuple[dict | None, Path | None]:
    try:
        run_dir = conforma_context_ops.discover_run_dir()
        context = conforma_context_ops.load(run_dir)
        return context, run_dir
    except (FileNotFoundError, KeyError):
        return None, None


def _resolve_config(args: argparse.Namespace) -> dict:
    context, run_dir = _load_context()

    namespace = _resolve(
        args.namespace, context, "resolve.tenant",
        env_var="KONFLUX_NAMESPACE", default=_DEFAULTS["namespace"],
    )
    cluster_domain = _resolve(
        args.cluster_domain, context, "resolve.cluster_domain",
        env_var="KONFLUX_CLUSTER_DOMAIN", default=_DEFAULTS["cluster_domain"],
    )
    environment = _resolve(
        args.environment, context, "environment",
        default=_DEFAULTS["environment"],
    )
    app_name = _resolve(
        None, context, "application.name",
        default=_DEFAULTS["app_name"],
    )

    if not cluster_domain:
        print(
            "Error: cluster_domain not resolved. Provide it via:\n"
            "  --cluster-domain, context.yaml (resolve.cluster_domain),\n"
            "  or KONFLUX_CLUSTER_DOMAIN env var.",
            file=sys.stderr,
        )
        sys.exit(1)

    version_input = args.version
    version_dir = None
    if version_input is None:
        version_dir = _resolve(None, context, "resolve.version_dir")
    if version_input is None and version_dir is None:
        print(
            "Error: no version provided and 'resolve.version_dir' not found in context.\n"
            "  Pass a version shortcode (e.g. 3.5) or exact PipelineRun name as argument,\n"
            "  or run resolve_release_context.py first to populate context.yaml.",
            file=sys.stderr,
        )
        sys.exit(1)

    tekton_domain = os.environ.get(
        "TEKTON_RESULTS_API_DOMAIN",
        f"tekton-results-tekton-results.apps.{cluster_domain}.openshiftapps.com",
    )
    api_base = f"https://{tekton_domain}/apis/results.tekton.dev/{TEKTON_RESULTS_API_VERSION}"

    return {
        "namespace": namespace,
        "cluster_domain": cluster_domain,
        "environment": environment,
        "app_name": app_name,
        "version_input": version_input,
        "version_dir": version_dir,
        "policy_type": args.type,
        "api_base": api_base,
        "run_dir": run_dir,
        "handover_file": args.handover,
        "output_file": args.output,
    }


# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------


def parse_version_shortcode(raw: str) -> str | None:
    """Normalize a user version shortcode into a version_dir slug (e.g. v3-5-ea-1).

    Returns None if the input doesn't look like a version shortcode.
    """
    text = raw.strip().lower()
    text = re.sub(r"^rhoai[\s.\-]*", "", text)
    text = re.sub(r"^v", "", text)
    text = re.sub(r"^(\d+)-(\d+)", r"\1.\2", text)

    ea_match = re.match(r"^(\d+\.\d+)[\s.\-]*ea[\s.\-]*(\d+)$", text)
    if ea_match:
        text = f"{ea_match.group(1)}-ea.{ea_match.group(2)}"

    if not re.match(r"^\d+\.\d+(-ea\.\d+)?$", text):
        return None

    return f"v{text}".replace(".", "-")


def version_dir_to_slug(version_dir: str) -> str:
    return version_dir.replace(".", "-")


# ---------------------------------------------------------------------------
# ITS prefix construction
# ---------------------------------------------------------------------------


def build_its_prefix(policy_type: str, app_name: str, environment: str, version_slug: str) -> str:
    if policy_type == "registry":
        return f"conforma-registry-{app_name}-{environment}-{version_slug}"
    elif policy_type == "chart":
        return f"conforma-registry-{app_name}-chart-{environment}-{version_slug}"
    elif policy_type == "fbc":
        return f"conforma-fbc-{app_name}-{environment}-{version_slug}"
    else:
        raise ValueError(f"Unknown policy type: {policy_type}")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _get_token() -> str:
    token = os.environ.get("KONFLUX_TOKEN")
    if token:
        return token
    try:
        proc = subprocess.run(
            ["oc", "whoami", "-t"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    print("Error: no auth token. Set KONFLUX_TOKEN or run 'oc login'.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# PipelineRun discovery
# ---------------------------------------------------------------------------


def _oc_list_pipelineruns(namespace: str) -> list[str]:
    try:
        proc = subprocess.run(
            [
                "oc", "get", "pipelinerun", "-n", namespace,
                "--sort-by=.metadata.creationTimestamp",
                "-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0:
            return [line for line in proc.stdout.strip().splitlines() if line]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def _search_tekton_api_for_name(
    api_base: str, namespace: str, token: str, name_pattern: str,
) -> str | None:
    url = f"{api_base}/parents/{namespace}/results/-/records"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"order_by": "create_time desc", "page_size": "100"},
            verify=False, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    regex = re.compile(f"^{re.escape(name_pattern)}-[a-z0-9]+$")
    for record in data.get("records", []):
        raw_value = record.get("data", {}).get("value")
        if not raw_value:
            continue
        try:
            import base64
            decoded = json.loads(base64.b64decode(raw_value))
            name = decoded.get("metadata", {}).get("name", "")
            if regex.match(name):
                return name
        except Exception:
            continue
    return None


def discover_pipelinerun(
    its_prefix: str,
    namespace: str,
    api_base: str,
    token: str,
) -> str | None:
    regex = re.compile(f"^{re.escape(its_prefix)}-[a-z0-9]+$")
    future_prefix = f"{its_prefix}-future"
    future_regex = re.compile(f"^{re.escape(future_prefix)}-[a-z0-9]+$")

    all_runs = _oc_list_pipelineruns(namespace)

    primary_matches = [r for r in all_runs if regex.match(r)]
    if primary_matches:
        return primary_matches[-1]

    future_matches = [r for r in all_runs if future_regex.match(r)]
    if future_matches:
        print(f"    ⚠️  No primary runs found. Using newest -future run.", file=sys.stderr)
        return future_matches[-1]

    print("    ⚠️  No live runs found. Searching Tekton Results API archive...", file=sys.stderr)

    archived = _search_tekton_api_for_name(api_base, namespace, token, its_prefix)
    if archived:
        return archived

    archived_future = _search_tekton_api_for_name(api_base, namespace, token, future_prefix)
    if archived_future:
        print(f"    ⚠️  Using archived -future run.", file=sys.stderr)
        return archived_future

    return None


# ---------------------------------------------------------------------------
# UUID resolution
# ---------------------------------------------------------------------------


def _resolve_pipelinerun_uuid(
    pipelinerun_name: str, namespace: str, api_base: str, token: str,
) -> str | None:
    try:
        proc = subprocess.run(
            ["oc", "get", "pipelinerun", pipelinerun_name, "-n", namespace,
             "-o", "jsonpath={.metadata.uid}"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip() and proc.stdout.strip() != "null":
            return proc.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    print("    ⚠️  Run pruned from live cluster. Searching Tekton Results API...", file=sys.stderr)
    cel_filter = f"data.metadata.name == '{pipelinerun_name}'"
    url = f"{api_base}/parents/{namespace}/results/-/records"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"filter": cel_filter},
            verify=False, timeout=30,
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
        if records:
            record_name = records[0].get("name", "")
            match = re.search(r"results/([0-9a-f-]+)", record_name)
            if match:
                return match.group(1)
    except (requests.RequestException, ValueError):
        pass

    return None


# ---------------------------------------------------------------------------
# Verify task log resolution
# ---------------------------------------------------------------------------


def _resolve_verify_log(
    pipelinerun_name: str,
    result_uuid: str,
    namespace: str,
    api_base: str,
    token: str,
) -> tuple[str | None, str | None]:
    """Returns (log_uuid, live_pod_name)."""
    log_uuid = None
    live_pod_name = None

    try:
        proc = subprocess.run(
            ["oc", "get", "taskrun", "-n", namespace,
             "-l", f"tekton.dev/pipelineRun={pipelinerun_name},tekton.dev/pipelineTask=verify",
             "-o", "jsonpath={.items[0].metadata.uid}"],
            capture_output=True, text=True, timeout=15,
        )
        uid = proc.stdout.strip()
        if proc.returncode == 0 and uid and uid != "null":
            log_uuid = uid
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        proc = subprocess.run(
            ["oc", "get", "taskrun", "-n", namespace,
             "-l", f"tekton.dev/pipelineRun={pipelinerun_name},tekton.dev/pipelineTask=verify",
             "-o", "jsonpath={.items[0].status.podName}"],
            capture_output=True, text=True, timeout=15,
        )
        pod = proc.stdout.strip()
        if proc.returncode == 0 and pod and pod != "null":
            live_pod_name = pod
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    if log_uuid:
        return log_uuid, live_pod_name

    print("    ⚠️  Task layer pruned. Requesting historical log index...", file=sys.stderr)
    url = f"{api_base}/parents/{namespace}/results/{result_uuid}/records"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"page_size": "100"},
            verify=False, timeout=30,
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
        for record in records:
            data_type = record.get("data_type", record.get("dataType", ""))
            summary_name = record.get("summary", {}).get("name", "")
            is_log = "Log" in data_type
            is_verify = "verify" in summary_name

            if not is_log and not is_verify:
                raw_value = record.get("data", {}).get("value")
                if raw_value:
                    try:
                        import base64
                        decoded = json.loads(base64.b64decode(raw_value))
                        meta_name = decoded.get("metadata", {}).get("name", "")
                        labels = decoded.get("metadata", {}).get("labels", {})
                        is_verify = (
                            "verify" in meta_name
                            or labels.get("tekton.dev/pipelineTask") == "verify"
                        )
                    except Exception:
                        pass

            if is_log or is_verify:
                record_name = record.get("name", "")
                parts = record_name.split("/")
                candidate = parts[-1] if parts else ""
                if candidate and candidate != result_uuid:
                    log_uuid = candidate
                    break
    except (requests.RequestException, ValueError):
        pass

    return log_uuid, live_pod_name


# ---------------------------------------------------------------------------
# Log extraction
# ---------------------------------------------------------------------------


def extract_report_from_log(log_text: str, step_name: str = STEP_NAME) -> str:
    report_lines: list[str] = []
    in_section = False
    marker_start = f"{step_name} :-"

    for line in log_text.splitlines():
        if line.startswith(marker_start):
            in_section = True
            continue
        if in_section and re.match(r"^step-.* :-", line):
            break
        if in_section:
            report_lines.append(line)

    return "\n".join(report_lines)


def _fetch_log_from_api(
    api_base: str, namespace: str, result_uuid: str, log_uuid: str, token: str,
) -> str:
    url = f"{api_base}/parents/{namespace}/results/{result_uuid}/logs/{log_uuid}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            verify=False, timeout=60,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        print(f"    ⚠️  Failed to fetch log from API: {exc}", file=sys.stderr)
        return ""


def _fetch_log_from_pod(pod_name: str, step_name: str, namespace: str) -> str:
    try:
        proc = subprocess.run(
            ["oc", "logs", pod_name, "-c", step_name, "-n", namespace],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode == 0:
            return proc.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


# ---------------------------------------------------------------------------
# Handover assembly
# ---------------------------------------------------------------------------


def build_handover(
    initial_state: dict,
    pipelinerun_name: str,
    namespace: str,
    report_path: str | None,
    error: str | None = None,
) -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = dict(initial_state)

    state.setdefault("metadata", {})
    state["metadata"]["pipeline_run"] = pipelinerun_name
    state["metadata"]["namespace"] = namespace
    state["metadata"].setdefault("created_at", timestamp)
    state["metadata"].setdefault("policy_source", "github.com/conforma/config//default")

    if report_path and error is None:
        state["report_fetch"] = {
            "status": "completed",
            "completed_at": timestamp,
            "raw_report_path": report_path,
            "error": None,
        }
    else:
        state["report_fetch"] = {
            "status": "failed",
            "completed_at": timestamp,
            "error": error or "Log payload returned empty.",
        }

    state.setdefault("violation_parse", None)
    state.setdefault("investigation", None)
    return state


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Conforma Tekton report from Konflux.",
    )
    parser.add_argument(
        "version", nargs="?", default=None,
        help="Version shortcode (e.g. 3.5, 3.5ea.2) or exact PipelineRun name.",
    )
    parser.add_argument(
        "--type", choices=POLICY_TYPES, default="registry",
        help="Policy type (default: registry).",
    )
    parser.add_argument("--namespace", default=None, help="Konflux namespace.")
    parser.add_argument("--cluster-domain", default=None, dest="cluster_domain",
                        help="Konflux cluster domain.")
    parser.add_argument("--environment", choices=["prod", "stage"], default=None,
                        help="Target environment.")
    parser.add_argument("--handover", default=None,
                        help="Path to existing handover JSON to update.")
    parser.add_argument("--output", default=None,
                        help="Path to write handover JSON (default: stdout).")
    args = parser.parse_args()

    config = _resolve_config(args)

    initial_state: dict = {}
    if config["handover_file"]:
        handover_path = Path(config["handover_file"])
        if handover_path.is_file():
            initial_state = json.loads(handover_path.read_text(encoding="utf-8"))
    elif not sys.stdin.isatty():
        initial_state = json.loads(sys.stdin.read())

    print("⏳ [1/4] Gathering authentication token...", file=sys.stderr)
    token = _get_token()

    version_input = config["version_input"]
    version_dir = config["version_dir"]

    is_shortcode = False
    if version_input is not None:
        slug = parse_version_shortcode(version_input)
        if slug is not None:
            is_shortcode = True
            version_slug = slug
        else:
            pipelinerun_name = version_input.removesuffix("-verify")
    elif version_dir is not None:
        is_shortcode = True
        version_slug = version_dir_to_slug(version_dir)

    if is_shortcode:
        its_prefix = build_its_prefix(
            config["policy_type"], config["app_name"],
            config["environment"], version_slug,
        )
        print(f"⏳ [Input Router] Searching for newest run matching {its_prefix}...", file=sys.stderr)

        pipelinerun_name_result = discover_pipelinerun(
            its_prefix, config["namespace"], config["api_base"], token,
        )
        if pipelinerun_name_result is None:
            msg = (
                f"Could not discover any Conforma {config['policy_type']} runs "
                f"for version '{version_input or version_dir}' "
                f"(prefix: {its_prefix})."
            )
            print(f"❌ Error: {msg}", file=sys.stderr)
            _write_failure(config, initial_state, msg)
            return 1
        pipelinerun_name = pipelinerun_name_result
        print(f"    🎯 Resolved target -> {pipelinerun_name}", file=sys.stderr)

    print("⏳ [2/4] Resolving PipelineRun UUID...", file=sys.stderr)
    result_uuid = _resolve_pipelinerun_uuid(
        pipelinerun_name, config["namespace"], config["api_base"], token,
    )
    if not result_uuid:
        msg = f"Could not locate PipelineRun '{pipelinerun_name}'."
        print(f"❌ Error: {msg}", file=sys.stderr)
        _write_failure(config, initial_state, msg)
        return 1
    print(f"    ✅ Resolved UUID: {result_uuid}", file=sys.stderr)

    print("⏳ [3/4] Resolving verify task log record...", file=sys.stderr)
    log_uuid, live_pod_name = _resolve_verify_log(
        pipelinerun_name, result_uuid, config["namespace"], config["api_base"], token,
    )
    if not log_uuid:
        msg = "Verification log tracking data is missing."
        print(f"❌ Error: {msg}", file=sys.stderr)
        _write_failure(config, initial_state, msg)
        return 1

    report_path = Path(f"/tmp/conforma-report-{result_uuid}.json")

    print("⏳ [4/4] Extracting log payload...", file=sys.stderr)
    raw_log = _fetch_log_from_api(
        config["api_base"], config["namespace"], result_uuid, log_uuid, token,
    )
    report_content = extract_report_from_log(raw_log)

    if not report_content and live_pod_name:
        print("    ⚠️  Archive empty. Reading from live pod...", file=sys.stderr)
        report_content = _fetch_log_from_pod(live_pod_name, STEP_NAME, config["namespace"])

    if report_content:
        report_path.write_text(report_content, encoding="utf-8")
        handover = build_handover(
            initial_state, pipelinerun_name, config["namespace"], str(report_path),
        )
        _write_step_status(config, pipelinerun_name, str(report_path), None)
    else:
        error_msg = "Log payload returned empty or unpopulated."
        handover = build_handover(
            initial_state, pipelinerun_name, config["namespace"], None, error=error_msg,
        )
        _write_step_status(config, pipelinerun_name, None, error_msg)

    _write_output(handover, config["output_file"])

    status = handover.get("report_fetch", {}).get("status", "unknown")
    if status == "completed":
        print(f"✅ Report saved to {report_path}", file=sys.stderr)
        return 0
    else:
        print(f"❌ Fetch failed: {handover['report_fetch'].get('error')}", file=sys.stderr)
        return 1


def _write_failure(config: dict, initial_state: dict, error_msg: str) -> None:
    handover = build_handover(
        initial_state, "", config["namespace"], None, error=error_msg,
    )
    _write_step_status(config, "", None, error_msg)
    _write_output(handover, config["output_file"])


def _write_step_status(
    config: dict,
    pipelinerun_name: str,
    report_path: str | None,
    error: str | None,
) -> None:
    run_dir = config.get("run_dir")
    if run_dir is None:
        return
    try:
        if error is None and report_path:
            conforma_context_ops.update_step(
                run_dir, "tekton_fetch", "completed",
                raw_report_path=report_path,
                pipeline_run=pipelinerun_name,
                policy_type=config["policy_type"],
            )
        else:
            conforma_context_ops.update_step(
                run_dir, "tekton_fetch", "failed",
                error=error or "Unknown error",
                pipeline_run=pipelinerun_name,
                failed_at=datetime.now(timezone.utc).isoformat(),
            )
    except Exception:
        pass


def _write_output(handover: dict, output_file: str | None) -> None:
    output = json.dumps(handover, indent=2)
    if output_file:
        Path(output_file).write_text(output + "\n", encoding="utf-8")
        print(f"🎯 Handover saved to: {output_file}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    sys.exit(main())
