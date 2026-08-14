#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Apply all onboarding-specific Jira metadata updates:
  - Strip template tokens from title, insert component name
  - Replace description table first data row with actual values
  - Add component-onboarding label

Works for both ODH and RHOAI, and for both existing and newly-created Jira tickets.
"""

import argparse
import base64
import json
import os
import sys
import urllib.request


def jira_request(url, *, email, token, method="GET", data=None):
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        return resp.status, json.loads(body) if body else {}


def main():
    p = argparse.ArgumentParser(description="Update Jira metadata for component onboarding")
    p.add_argument("jira_url", help="e.g. https://redhat.atlassian.net/browse/RHOAIENG-1234")
    p.add_argument("--component-name", required=True)
    p.add_argument("--product-context", required=True, choices=["ODH", "RHOAI"])
    p.add_argument("--repo-url", required=True)
    p.add_argument("--repo-branch", required=True)
    p.add_argument("--context-path", required=True)
    p.add_argument("--dockerfile-path", required=True)
    p.add_argument("--short-description", default="")
    p.add_argument("--architectures", default="")
    p.add_argument(
        "--target-version",
        default="",
        help=(
            "Version name to set as Target Version (customfield_10855) on the Jira issue. "
            "For RHOAI pass target_rhoai_version (e.g. '3.5' or '3.5-ea-1'). "
            "For ODH Release pass odh_release_tag (e.g. '2.21.0'). "
            "Omit for ODH CI builds where no fixed version applies."
        ),
    )
    args = p.parse_args()

    email = os.environ.get("JIRA_USER_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not email or not token:
        print("ERROR: JIRA_USER_EMAIL and JIRA_API_TOKEN must be set", file=sys.stderr)
        sys.exit(1)

    jira_server = os.environ.get("JIRA_SERVER", "https://redhat.atlassian.net")
    jira_id = args.jira_url.rstrip("/").split("/")[-1]
    api_base = f"{jira_server}/rest/api/2/issue/{jira_id}"

    # Derived values
    if args.product_context == "ODH":
        quay_image = f"quay.io/opendatahub/{args.component_name}"
    else:
        quay_image = f"quay.io/rhoai/{args.component_name}-rhel9"

    clean_ctx = args.context_path.rstrip("/").lstrip("./")
    if clean_ctx and clean_ctx != ".":
        dockerfile_link = f"{args.repo_url}/blob/{args.repo_branch}/{clean_ctx}/{args.dockerfile_path}"
    else:
        dockerfile_link = f"{args.repo_url}/blob/{args.repo_branch}/{args.dockerfile_path}"

    # Fetch current issue fields
    _, issue = jira_request(f"{api_base}?fields=summary,description,labels,components,customfield_10855", email=email, token=token)
    current_summary = issue["fields"]["summary"]
    description = issue["fields"].get("description") or ""
    current_labels = issue["fields"].get("labels") or []

    warnings = []

    # --- Update title ---
    new_summary = current_summary
    for tmpl_token in ("[TEMPLATE] ", "[Template] "):
        new_summary = new_summary.replace(tmpl_token, "")
    for name_token in ("[COMPONENT NAME]", "[Component Name]"):
        new_summary = new_summary.replace(name_token, args.component_name)

    if new_summary != current_summary:
        try:
            payload = json.dumps({"fields": {"summary": new_summary}}).encode()
            jira_request(api_base, method="PUT", data=payload, email=email, token=token)
            print(f"  Title updated: {new_summary}")
        except Exception as exc:
            warnings.append(f"WARN: Could not update title — rename manually to: {new_summary} ({exc})")
    else:
        print(f"  Title unchanged: {current_summary}")

    # --- Update description table ---
    # ODH template:  ||*Upstream Git Repo*||...
    # RHOAI template: ||*Image / Quay Repo Name*||...
    lines = description.split("\n")
    odh_header_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("||*Upstream Git Repo*||")),
        None,
    )
    rhoai_header_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("||*Image / Quay Repo Name*||")),
        None,
    )

    if odh_header_idx is not None:
        values_row = (
            f"| {args.repo_url} "
            f"| {quay_image} "
            f"| {args.context_path} "
            f"| [{args.dockerfile_path}|{dockerfile_link}] "
            f"| |"
        )
        header_idx = odh_header_idx
    elif rhoai_header_idx is not None:
        arch_str = args.architectures.replace(",", ", ") if args.architectures else ""
        values_row = (
            f"| {quay_image} "
            f"| {args.short_description} "
            f"| {arch_str} "
            f"| {args.context_path} "
            f"| [{args.dockerfile_path}|{dockerfile_link}] "
            f"| |"
        )
        header_idx = rhoai_header_idx
    else:
        header_idx = None

    if header_idx is not None:
        # Replace first data row; drop any additional | rows after it
        lines[header_idx + 1] = values_row
        i = header_idx + 2
        while i < len(lines) and lines[i].startswith("|"):
            lines.pop(i)

        new_desc = "\n".join(lines)
        try:
            payload = json.dumps({"fields": {"description": new_desc}}).encode()
            jira_request(api_base, method="PUT", data=payload, email=email, token=token)
            print("  Description table updated.")
        except Exception as exc:
            warnings.append(
                f"WARN: Could not update description table ({exc}). Update manually:\n"
                f"  Image / Quay Repo Name   → {quay_image}\n"
                f"  Build Context            → {args.context_path}\n"
                f"  Dockerfile Link or Path  → {dockerfile_link}"
            )
    else:
        print("  No known description table found — skipping table update.")

    # --- Set Target Version (both products when --target-version is provided) ---
    if args.target_version:
        target_version_name = args.target_version
        try:
            _, project_versions = jira_request(
                f"{jira_server}/rest/api/2/project/{jira_id.split('-')[0]}/versions",
                email=email, token=token,
            )
            valid_names = {v["name"] for v in project_versions}
            if target_version_name in valid_names:
                current_tv = issue["fields"].get("customfield_10855") or []
                current_tv_names = {v["name"] for v in current_tv}
                if target_version_name not in current_tv_names:
                    payload = json.dumps({"update": {"customfield_10855": [{"add": {"name": target_version_name}}]}}).encode()
                    jira_request(api_base, method="PUT", data=payload, email=email, token=token)
                    print(f"  Target Version added: {target_version_name}")
                else:
                    print(f"  Target Version already set: {target_version_name}")
            else:
                warnings.append(
                    f"WARN: Target Version '{target_version_name}' not found in project. "
                    f"Set it manually in Jira."
                )
        except Exception as exc:
            warnings.append(f"WARN: Could not set Target Version '{target_version_name}' ({exc}). Set manually in Jira.")

    # --- Ensure DevOps component is present ---
    current_components = issue["fields"].get("components") or []
    current_component_names = {c["name"] for c in current_components}
    if "DevOps" not in current_component_names:
        try:
            payload = json.dumps({"update": {"components": [{"add": {"name": "DevOps"}}]}}).encode()
            jira_request(api_base, method="PUT", data=payload, email=email, token=token)
            print("  Component added: DevOps")
        except Exception as exc:
            warnings.append(f"WARN: Could not add 'DevOps' component ({exc}). Add manually.")
    else:
        print("  Component already present: DevOps")

    # --- Add labels ---
    labels_to_add = ["component-onboarding", "devops-onboarding"]
    for label in labels_to_add:
        if label not in current_labels:
            try:
                payload = json.dumps({"fields": {"labels": current_labels + [label]}}).encode()
                jira_request(api_base, method="PUT", data=payload, email=email, token=token)
                current_labels.append(label)
                print(f"  Label added: {label}")
            except Exception as exc:
                warnings.append(f"WARN: Could not add '{label}' label ({exc}). Add manually.")
        else:
            print(f"  Label already present: {label}")

    for w in warnings:
        print(w)

    print(f"Done. {jira_id} updated.")


if __name__ == "__main__":
    main()
