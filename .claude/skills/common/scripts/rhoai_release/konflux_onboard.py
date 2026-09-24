"""CLI entry point and main workflow orchestration."""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from constants import (
    AUTO_GENERATED_RHOAI_TENANT,
    MR_BASE_URL,
    MR_DOTENV_FILENAME,
    REPO_BRANCH,
    RPA_PRODUCT_BASE,
    RPA_SERVICE_BASE,
    TENANT_BASE,
    TENANT_KUSTOMIZATION,
)
from gitlab_ops import create_merge_request_safe
from file_ops import (
    copy_version_directory,
    create_rpa_files,
    rename_files,
    run_build_manifests,
    update_file_versions,
    update_kustomization,
)
from git_ops import clone_repo, commit_and_push, create_branch, ensure_latest_main, show_changes
from util import is_ea_version, parse_version_input

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _remove_local_clone(repo_dir: Path) -> None:
    """Delete the cloned konflux-release-data tree after push + MR step."""
    if not repo_dir.is_dir():
        return
    try:
        shutil.rmtree(repo_dir)
        logger.info("Removed local clone: %s", repo_dir)
    except OSError as e:
        logger.warning("Could not remove local clone %s: %s", repo_dir, e)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Automate RHOAI minor version onboarding in konflux-release-data."
    )
    parser.add_argument(
        "previous_version",
        help='Previous version (e.g. "rhoai-3.4", "rhoai-3.4.ea.1")',
    )
    parser.add_argument(
        "new_version",
        help='New version (e.g. "rhoai-3.5", "rhoai-3.4.ea.2" for ea.1->ea.2)',
    )
    parser.add_argument(
        "--repo-dir",
        default="konflux-release-data",
        help="Local directory to clone into (default: konflux-release-data)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform all steps and show changes (git status + diff), but do not commit or push",
    )
    args = parser.parse_args()

    args.is_ea = is_ea_version(args.previous_version) or is_ea_version(args.new_version)

    (
        args.prev_version,
        args.prev_version_dash,
        args.prev_minor_dir,
    ) = parse_version_input(args.previous_version)
    (
        args.new_version_parsed,
        args.new_version_dash,
        args.new_minor_dir,
    ) = parse_version_input(args.new_version)

    args.previous_version = args.prev_version
    args.previous_version_dash = args.prev_version_dash
    args.previous_minor_dir = args.prev_minor_dir
    args.new_version = args.new_version_parsed

    return args


def main():
    """Run the full onboarding workflow."""
    # Load local .env automatically for local runs (CI env vars still take precedence).
    load_dotenv()
    args = parse_args()
    repo_dir = Path(args.repo_dir).resolve()

    try:
        clone_repo(repo_dir)
        ensure_latest_main(repo_dir)
        branch_name = create_branch(repo_dir)

        new_tenant_dir = copy_version_directory(
            repo_dir,
            TENANT_BASE,
            args.previous_minor_dir,
            args.new_minor_dir,
        )
        rename_files(new_tenant_dir, args.previous_minor_dir, args.new_minor_dir)
        prev_ea_display = (
            args.previous_version.replace(".ea.", "-ea.") if is_ea_version(args.previous_version) else None
        )
        new_ea_display = (
            args.new_version.replace(".ea.", "-ea.") if is_ea_version(args.new_version) else None
        )
        update_file_versions(
            new_tenant_dir,
            args.previous_version,
            args.new_version,
            args.previous_version_dash,
            args.new_version_dash,
            previous_ea_display=prev_ea_display,
            new_ea_display=new_ea_display,
        )

        update_kustomization(repo_dir, TENANT_KUSTOMIZATION, args.new_minor_dir)

        create_rpa_files(
            repo_dir,
            RPA_PRODUCT_BASE,
            args.previous_version_dash,
            args.new_version_dash,
            args.previous_version,
            args.new_version,
            is_ea=args.is_ea,
            previous_ea_display=prev_ea_display,
            new_ea_display=new_ea_display,
        )
        create_rpa_files(
            repo_dir,
            RPA_SERVICE_BASE,
            args.previous_version_dash,
            args.new_version_dash,
            args.previous_version,
            args.new_version,
            is_ea=args.is_ea,
            previous_ea_display=prev_ea_display,
            new_ea_display=new_ea_display,
        )

        # Regenerate tenants-config/auto-generated/... (must run after all edits, before git add/commit).
        run_build_manifests(repo_dir)

        if args.dry_run:
            show_changes(repo_dir)
            logger.info("Dry run complete. No commit or push.")
            if os.environ.get("CI", "").lower() == "true":
                Path(MR_DOTENV_FILENAME).write_text(
                    "MERGE_REQUEST_URL=\nMERGE_REQUEST_REF=\nMERGE_REQUEST_IID=\n",
                    encoding="utf-8",
                )
                logger.info("Wrote empty %s (dry run; no MR)", MR_DOTENV_FILENAME)
            _remove_local_clone(repo_dir)
        else:
            # Hand-edited trees + only rhoai-tenant under auto-generated (not tenants-config/auto-generated/ broadly).
            paths_to_add = [
                TENANT_BASE,
                RPA_PRODUCT_BASE,
                RPA_SERVICE_BASE,
                AUTO_GENERATED_RHOAI_TENANT,
            ]
            commit_and_push(
                repo_dir,
                args.new_version,
                branch_name,
                paths_to_add=paths_to_add,
                dry_run=False,
            )
            mr_title = f"Add Konflux release configuration for RHOAI v{args.new_version}"
            mr_info = create_merge_request_safe(
                branch_name,
                mr_title,
                target_branch=REPO_BRANCH,
            )
            in_ci = os.environ.get("CI", "").lower() == "true"
            allow_manual = os.environ.get("ALLOW_MANUAL_MR_FALLBACK", "").lower() in (
                "1",
                "true",
                "yes",
            )
            if not mr_info:
                if in_ci and not allow_manual:
                    logger.error(
                        "Merge request was not created via API. In CI, set KONFLUX_REPO_TOKEN with "
                        "'api' scope, or set ALLOW_MANUAL_MR_FALLBACK=true to allow the compose-URL fallback."
                    )
                    sys.exit(1)
                manual_url = MR_BASE_URL + branch_name
                logger.info("Using manual merge request URL (API skipped or failed): %s", manual_url)
                print("\n" + "=" * 60)
                print("Merge request (open manually):")
                print(manual_url)
                print("=" * 60)
                if in_ci:
                    Path(MR_DOTENV_FILENAME).write_text(
                        f"MERGE_REQUEST_URL={manual_url}\n"
                        "MERGE_REQUEST_REF=\n"
                        "MERGE_REQUEST_IID=\n",
                        encoding="utf-8",
                    )
                    logger.info("Wrote %s (manual MR link; API unavailable)", MR_DOTENV_FILENAME)
            else:
                print("\n" + "=" * 60)
                print("Merge request reference:")
                print(mr_info.reference)
                print("Merge request URL:")
                print(mr_info.web_url)
                print("=" * 60)
                if in_ci:
                    dotenv_path = Path(MR_DOTENV_FILENAME)
                    dotenv_path.write_text(
                        "MERGE_REQUEST_URL={}\nMERGE_REQUEST_REF={}\nMERGE_REQUEST_IID={}\n".format(
                            mr_info.web_url,
                            mr_info.reference,
                            mr_info.iid,
                        ),
                        encoding="utf-8",
                    )
                    logger.info("Wrote %s for CI dotenv artifact", MR_DOTENV_FILENAME)

            _remove_local_clone(repo_dir)

    except FileNotFoundError as e:
        logger.error("File/directory not found: %s", e)
        sys.exit(1)
    except RuntimeError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        sys.exit(1)
