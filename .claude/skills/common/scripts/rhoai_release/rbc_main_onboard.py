"""
RHOAI **main** onboarding — **add-only** (does not remove or rename existing OCP / Tekton files).

**1. Catalog**

Copy ``catalog/<previous_train>/`` → ``catalog/<next_train>/`` with ``shutil.copytree`` only.
**No** edits under the new tree (no newline fixes, no search/replace). Bytes inside files stay as in the source folder.

**2. Tekton (``.tekton/``)**

For each ``rhoai-fbc-fragment-<previous_seg>-ocp-*.yaml``:

- Read the existing file as a **template**.
- Write a **new** file whose basename uses ``<next_seg>`` (and updated version strings inside).
- **Leave the template files unchanged** on disk (no ``git mv``, no delete).

**3. Git (``main`` branch onboarding — not release-branch automation)**

Clone ``RBC_MAIN_REPO`` and set ``origin`` to that URL. Check out the **default branch** (usually ``main`` —
``MAIN_BRANCH``), create a **new topic branch**, add **only** the new catalog tree + new Tekton files +
optional ``builds/force-trigger-<next>.txt``, push that topic branch to ``origin``, open a PR **into** the base
branch (default ``main`` via ``RBC_PR_BASE``). This flow adds train content on top of ``main``; it does **not**
create or merge release-line branches like ``rbc_release``.

**Testing / duplicates:** Use a distinct ``RBC_MAIN_HEAD_PREFIX`` (and branch prefix/suffix) so automation branches
do not collide with real work. Catalog: set ``RBC_REPLACE_EXISTING_CATALOG=1`` only if you intend to overwrite an
existing train folder. Tekton: existing target YAMLs are skipped unless ``RBC_REPLACE_EXISTING_TEKTON=1``.

Usage::

    # From repo root:
    python -m src.rbc_main_onboard <previous_train> <next_train>
    # Or from ``src/`` (repo root is added to ``sys.path`` automatically):
    python rbc_main_onboard.py <previous_train> <next_train> [--dry-run]

``--dry-run`` or ``RBC_DRY_RUN=1``: show git status + diff after edits; no commit, push, or PR.

Loads ``.env`` from repo root. ``GITHUB_TOKEN`` embeds into HTTPS Git URLs when ``RBC_GIT_USE_GITHUB_TOKEN=1`` (default)
so ``git`` does not prompt. Default ``RBC_REBASE_ONTO_LATEST=1`` rebases the topic branch onto ``RBC_PR_BASE`` before push. Optional variables override defaults in ``rbc_build_config_constants``. ``GITHUB_TOKEN`` must be set only in ``.env`` or CI.

**EA → GA (same ``x.y``):** On ``main``, GA fragment YAMLs often already exist. If the computed
target path already exists, the script **skips** that file (no error). Set
``RBC_REPLACE_EXISTING_TEKTON=1`` to rewrite those files from the EA template. If the only templates
are already GA-named (fallback) and ``src == dst``, each file is skipped the same way.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import find_dotenv, load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if __package__ is None:
    _root = str(_REPO_ROOT)
    if _root not in sys.path:
        sys.path.insert(0, _root)

load_dotenv(_REPO_ROOT / ".env")
_env_walk = find_dotenv()
if _env_walk:
    load_dotenv(_env_walk)

import rbc_build_config_constants as constants
from rbc_release import (
    GITHUB_TOKEN,
    MAIN_REPO,
    assert_origin_is_main_repo,
    build_expanded_mapping,
    clone_repo,
    dry_run_requested,
    ensure_pr_base_on_origin,
    github_pr_target_repo,
    have_remote_branch,
    normalize_self_managed_docs_url_version,
    push_to_origin,
    rebase_onto_latest_enabled,
    replace_all,
    replace_tekton_yaml_content,
    setup_origin,
    show_working_tree_changes,
    try_fetch_branch,
)

CATALOG_DIR = "catalog"
TEKTON_DIR = constants.TEKTON_DIR
BUILDS_DIR = "builds"
TEKTON_FRAGMENT_GLOB = "rhoai-fbc-fragment-{seg}-ocp-*.yaml"


def _truthy(name: str) -> bool:
    default = getattr(constants, name, "")
    return constants.env_or_default(name, default).strip().lower() in ("1", "true", "yes")


def skip_ci_from_env() -> bool:
    v = constants.env_or_default("RBC_SKIP_CI", constants.RBC_SKIP_CI).strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def replace_existing_catalog_ok() -> bool:
    return _truthy("RBC_REPLACE_EXISTING_CATALOG")


def replace_existing_tekton_ok() -> bool:
    return _truthy("RBC_REPLACE_EXISTING_TEKTON")


def no_zstream_reset() -> bool:
    return _truthy("RBC_NO_ZSTREAM_RESET")


def no_auto_replace_ea_ga() -> bool:
    return _truthy("RBC_NO_AUTO_REPLACE_EA_TO_GA")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Train:
    catalog_dir: str
    tekton_seg: str
    maj: str
    minor: str
    ea: str | None


def _strip_rhoai_prefix(s: str) -> str:
    s = s.strip()
    if s.lower().startswith("rhoai-"):
        return s[6:].lstrip()
    return s


def normalize_train_token(s: str) -> str:
    s = s.strip()
    m = re.match(r"^(\d+)-(\d+)(?:-ea[.\-]?(\d+))?$", s, re.IGNORECASE)
    if m:
        maj, min_, ea = m.group(1), m.group(2), m.group(3)
        return f"{maj}.{min_}-ea.{ea}" if ea else f"{maj}.{min_}"
    return s


def parse_train(arg: str) -> Train:
    s = normalize_train_token(_strip_rhoai_prefix(arg))
    m = re.match(r"^(\d+)\.(\d+)(?:[-.]ea[.]?(\d+))?$", s, re.IGNORECASE)
    if not m:
        print(
            "ERROR: cannot parse train from",
            repr(arg),
            "— use e.g. rhoai-3.4, rhoai-3.4-ea.2",
        )
        sys.exit(1)
    maj, min_, ea = m.group(1), m.group(2), m.group(3)
    if ea:
        catalog_dir = f"rhoai-{maj}.{min_}-ea.{ea}"
        tekton_seg = f"rhoai-{maj}{min_}-ea{ea}"
    else:
        catalog_dir = f"rhoai-{maj}.{min_}"
        tekton_seg = f"rhoai-{maj}{min_}"
    return Train(
        catalog_dir=catalog_dir,
        tekton_seg=tekton_seg,
        maj=maj,
        minor=min_,
        ea=ea,
    )


def rhoai_public_slug(t: Train) -> str:
    if t.ea:
        return f"rhoai-{t.maj}.{t.minor}-ea.{t.ea}"
    return f"rhoai-{t.maj}.{t.minor}"


def target_rhoai_version_value(t: Train) -> str:
    if t.ea:
        return f"{t.maj}.{t.minor}.0-ea.{t.ea}"
    return f"{t.maj}.{t.minor}.0"


def validate_progression(old: Train, new: Train, a: str, b: str) -> None:
    if _truthy("RBC_SKIP_PROGRESSION_CHECK"):
        return
    oi = (int(old.maj), int(old.minor))
    ni = (int(new.maj), int(new.minor))
    if ni < oi:
        print(
            "ERROR: argv[2] has a lower major.minor than argv[1].\n"
            f"  copy FROM = {a!r}  copy TO = {b!r}\n"
            "Set RBC_SKIP_PROGRESSION_CHECK=1 to bypass."
        )
        sys.exit(1)
    if ni > oi:
        return
    if old.ea is None and new.ea is None:
        print(f"ERROR: duplicate GA train {old.maj}.{old.minor}.\n  {a!r} → {b!r}")
        sys.exit(1)
    if old.ea is not None and new.ea is None:
        return
    if old.ea is None and new.ea is not None:
        return
    if int(new.ea) <= int(old.ea):
        print(
            f"ERROR: on {old.maj}.{old.minor}, EA index must increase.\n  {a!r} → {b!r}"
        )
        sys.exit(1)


def is_ea_to_ga_same_xy(old: Train, new: Train) -> bool:
    return (
        not no_auto_replace_ea_ga()
        and old.ea is not None
        and new.ea is None
        and old.maj == new.maj
        and old.minor == new.minor
    )


def may_overwrite_catalog_dest(old: Train, new: Train) -> bool:
    return replace_existing_catalog_ok() or is_ea_to_ga_same_xy(old, new)


# ---------------------------------------------------------------------------
# Catalog — copy folder only, contents unchanged
# ---------------------------------------------------------------------------


def step_copy_catalog_only(old: Train, new: Train) -> None:
    src = os.path.join(CATALOG_DIR, old.catalog_dir)
    dst = os.path.join(CATALOG_DIR, new.catalog_dir)
    if not os.path.isdir(src):
        print(f"ERROR: missing source catalog folder {src}/")
        sys.exit(1)
    if os.path.exists(dst):
        if not may_overwrite_catalog_dest(old, new):
            print(
                f"ERROR: destination already exists: {dst}/\n"
                "Use RBC_REPLACE_EXISTING_CATALOG=1, or EA→GA same x.y (auto)."
            )
            sys.exit(1)
        if is_ea_to_ga_same_xy(old, new):
            print(f"EA→GA same train: replacing {dst}/ from {src}/")
        else:
            print(f"RBC_REPLACE_EXISTING_CATALOG: replacing {dst}/ from {src}/")
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)
    print(f"Catalog: copied (contents unchanged) {src}/ → {dst}/")


# ---------------------------------------------------------------------------
# Tekton — new files only; templates left on disk
# ---------------------------------------------------------------------------


def build_string_mapping(old: Train, new: Train) -> dict[str, str]:
    def add(m: dict[str, str], o: str, n: str) -> None:
        if o and n and o != n:
            m.setdefault(o, n)

    m: dict[str, str] = {}
    add(m, f"catalog/{old.catalog_dir}/", f"catalog/{new.catalog_dir}/")
    add(m, f"catalog/{old.catalog_dir}", f"catalog/{new.catalog_dir}")
    add(
        m,
        f"builds/force-trigger-{old.catalog_dir}.txt",
        f"builds/force-trigger-{new.catalog_dir}.txt",
    )
    add(m, rhoai_public_slug(old), rhoai_public_slug(new))
    add(m, old.tekton_seg, new.tekton_seg)
    return m


def build_main_tekton_mapping(old: Train, new: Train) -> dict[str, str]:
    pe = f"ea.{old.ea}" if old.ea else None
    ne = f"ea.{new.ea}" if new.ea else None
    merged = dict(
        build_expanded_mapping(old.maj, old.minor, new.maj, new.minor, pe, ne)
    )
    merged.update(build_string_mapping(old, new))
    return merged


def reset_minor_bump_patch_to_zero(text: str, old: Train, new: Train) -> str:
    """Before mapping: old train z-stream → new minor ``.0``."""
    if no_zstream_reset():
        return text
    if old.maj == new.maj and old.minor == new.minor:
        return text
    pat = re.compile(rf"\b{re.escape(old.maj)}\.{re.escape(old.minor)}\.\d+\b")
    return pat.sub(f"{new.maj}.{new.minor}.0", text)


def reset_new_minor_zstream_to_ga_baseline(text: str, old: Train, new: Train) -> str:
    """After mapping: if ``2.16``→``2.17`` turned ``2.16.4`` into ``2.17.4``, force ``2.17.0``."""
    if no_zstream_reset():
        return text
    if old.maj == new.maj and old.minor == new.minor:
        return text
    pat = re.compile(rf"\b{re.escape(new.maj)}\.{re.escape(new.minor)}\.\d+\b")
    return pat.sub(f"{new.maj}.{new.minor}.0", text)


def patch_konflux_rhoai_version(text: str, value: str) -> str:
    return re.sub(
        r"(?m)(-\s+name:\s+rhoai-version\s*\n\s+value:\s*)([\"'])([^\"']+)\2",
        lambda mm: f"{mm.group(1)}{mm.group(2)}{value}{mm.group(2)}",
        text,
        count=1,
    )


def discover_tekton_templates(old: Train, new: Train) -> list[str]:
    p_old = os.path.join(TEKTON_DIR, TEKTON_FRAGMENT_GLOB.format(seg=old.tekton_seg))
    found = sorted(glob.glob(p_old))
    if found:
        return found
    if is_ea_to_ga_same_xy(old, new):
        p_ga = os.path.join(TEKTON_DIR, TEKTON_FRAGMENT_GLOB.format(seg=new.tekton_seg))
        fb = sorted(glob.glob(p_ga))
        if fb:
            print(
                "NOTE: No Tekton files for previous train name.\n"
                f"  Tried: {p_old}\n"
                f"Using GA-named templates: {p_ga}"
            )
            return fb
    print(f"ERROR: no Tekton files matching {p_old!r}")
    sys.exit(1)


def step_write_new_tekton_copies(old: Train, new: Train) -> list[str]:
    if not os.path.isdir(TEKTON_DIR):
        print(f"ERROR: missing {TEKTON_DIR}/")
        sys.exit(1)

    sources = discover_tekton_templates(old, new)
    mapping = build_main_tekton_mapping(old, new)
    ver = target_rhoai_version_value(new)
    written: list[str] = []

    for src in sources:
        directory, base = os.path.split(src)
        new_base = replace_all(base, mapping)
        dst = os.path.join(directory, new_base)
        ea_ga = is_ea_to_ga_same_xy(old, new)

        if os.path.normpath(src) == os.path.normpath(dst):
            if ea_ga:
                print(
                    f"Tekton: skip {src!r} (EA→GA: template path already GA-named on main)."
                )
                continue
            print(f"ERROR: source and destination are the same ({src!r}). Trains must differ.")
            sys.exit(1)

        if os.path.exists(dst):
            if replace_existing_tekton_ok():
                print(f"RBC_REPLACE_EXISTING_TEKTON: overwriting {dst}")
            elif ea_ga:
                print(
                    f"Tekton: skip {dst!r} (EA→GA: file already on main; "
                    "set RBC_REPLACE_EXISTING_TEKTON=1 to refresh from EA template)."
                )
                continue
            else:
                print(
                    f"ERROR: Tekton file already exists: {dst}\n"
                    "Set RBC_REPLACE_EXISTING_TEKTON=1 to overwrite."
                )
                sys.exit(1)

        with open(src, encoding="utf-8", newline="") as f:
            text = f.read()
        text = reset_minor_bump_patch_to_zero(text, old, new)
        text = replace_tekton_yaml_content(text, mapping)
        text = normalize_self_managed_docs_url_version(text)
        text = reset_new_minor_zstream_to_ga_baseline(text, old, new)
        text = patch_konflux_rhoai_version(text, ver)
        if not text.endswith("\n"):
            text += "\n"
        with open(dst, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"Tekton (new file, template unchanged): {dst}  ←  {src}")
        written.append(dst)

    return written


def step_force_trigger(new: Train) -> str | None:
    path = os.path.join(BUILDS_DIR, f"force-trigger-{new.catalog_dir}.txt")
    os.makedirs(BUILDS_DIR, exist_ok=True)
    if os.path.isfile(path):
        return path
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = (
        "# Placeholder for pathChanged() triggers (FBC / catalog pipelines).\n"
        f"# Created by src.rbc_main_onboard at {ts} (UTC).\n"
        f"train={new.catalog_dir}\n"
    )
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    print(f"Created {path}")
    return path


# ---------------------------------------------------------------------------
# Git (product repo: origin = RBC_MAIN_REPO)
# ---------------------------------------------------------------------------


def resolved_git_head_branch(logical: str) -> str:
    p = constants.env_or_default("RBC_BRANCH_PREFIX", constants.RBC_BRANCH_PREFIX)
    if "RBC_BRANCH_SUFFIX" in os.environ:
        s = os.environ["RBC_BRANCH_SUFFIX"]
    else:
        s = constants.RBC_BRANCH_SUFFIX
    return f"{p}{logical}{s}"


def fetch_ref(remote: str, branch: str) -> bool:
    r = subprocess.run(
        ["git", "fetch", remote, f"{branch}:refs/remotes/{remote}/{branch}"],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def have_ref(remote: str, branch: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/remotes/{remote}/{branch}"],
            capture_output=True,
        ).returncode
        == 0
    )


def checkout_tracking_main() -> None:
    mb = constants.MAIN_BRANCH
    if not fetch_ref("origin", mb):
        print(f"ERROR: cannot fetch {mb!r} from origin ({MAIN_REPO}).")
        sys.exit(1)
    if not have_ref("origin", mb):
        print(f"ERROR: branch {mb!r} not found on origin.")
        sys.exit(1)
    run(["git", "checkout", "-B", mb, f"origin/{mb}"])


def new_branch(name: str) -> None:
    run(["git", "checkout", "-B", name])


def commit_and_push(
    head: str, paths: list[str], *, rebase_onto_base: str | None = None
) -> None:
    """Commit, optionally rebase onto latest ``RBC_PR_BASE`` (``RBC_REBASE_ONTO_LATEST``), then push."""
    exist = [p for p in paths if os.path.isfile(p) or os.path.isdir(p)]
    if not exist:
        print("ERROR: nothing to stage.")
        sys.exit(1)
    run(["git", "add", "--"] + exist)
    st = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    committed = False
    if not st.stdout.strip():
        print("Nothing to commit.")
    else:
        msg = f"Onboard {head}: catalog copy + new Tekton YAMLs (add-only)"
        if skip_ci_from_env():
            msg += " [skip ci]"
        run(["git", "commit", "-m", msg])
        committed = True

    if committed and rebase_onto_base and rebase_onto_latest_enabled():
        if not try_fetch_branch("origin", rebase_onto_base) or not have_remote_branch(
            "origin", rebase_onto_base
        ):
            print(
                f"ERROR: cannot fetch origin/{rebase_onto_base} for rebase. "
                "Set RBC_REBASE_ONTO_LATEST=0 to skip."
            )
            sys.exit(1)
        print(
            f"\nRebasing onto origin/{rebase_onto_base} (set RBC_REBASE_ONTO_LATEST=0 to skip).\n"
        )
        try:
            run(["git", "rebase", f"origin/{rebase_onto_base}"])
        except subprocess.CalledProcessError:
            print(
                "ERROR: git rebase failed — resolve conflicts or set RBC_REBASE_ONTO_LATEST=0."
            )
            sys.exit(1)
        push_to_origin(head, force_with_lease=True)
    else:
        push_to_origin(head, force=True)


def open_pr(head: str, base: str, prev: str, nxt: str) -> None:
    if head == base:
        print("ERROR: head == base")
        sys.exit(1)
    repo = github_pr_target_repo()
    url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title": f"Onboard {nxt} (from {prev}) [add-only]",
        "head": head,
        "base": base,
        "body": (
            f"**Main-branch onboarding** (`rbc_main_onboard`): merge **`{head}`** into **`{base}`** on `{repo}`.\n\n"
            "This PR adds new catalog/Tekton files on top of the default branch — **not** a release-branch "
            "bump (use `rbc_release` for release lines).\n\n"
            f"- Catalog: copied `{prev}/` → `{nxt}/` (folder name only; **no** in-file edits).\n"
            "- Tekton: **new** `rhoai-fbc-fragment-...` YAMLs from previous train templates; "
            "existing OCP fragment files **not** removed.\n"
        ),
    }
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    try:
        r.raise_for_status()
    except requests.HTTPError:
        print("GitHub API error:", r.status_code, r.text)
        sys.exit(1)
    print("PR:", r.json().get("html_url", ""))


def main() -> None:
    if not GITHUB_TOKEN:
        print("ERROR: set GITHUB_TOKEN")
        sys.exit(1)
    pos = [a for a in sys.argv[1:] if a != "--dry-run"]
    if len(pos) != 2:
        print(
            "Usage: python -m src.rbc_main_onboard <previous_train> <next_train> [--dry-run]\n"
            "  Adds new catalog folder + new Tekton YAMLs; does not delete previous OCP YAMLs.\n"
            "  --dry-run / RBC_DRY_RUN=1 — show changes only.\n"
            "Examples:\n"
            "  python -m src.rbc_main_onboard rhoai-3.4-ea.1 rhoai-3.4-ea.2\n"
            "  python -m src.rbc_main_onboard rhoai-2.16 rhoai-2.17"
        )
        sys.exit(1)

    dry = dry_run_requested()
    prev_arg, next_arg = pos[0], pos[1]
    old = parse_train(prev_arg)
    new = parse_train(next_arg)
    validate_progression(old, new, prev_arg, next_arg)

    prefix = constants.env_or_default("RBC_MAIN_HEAD_PREFIX", constants.RBC_MAIN_HEAD_PREFIX)
    logical = f"{prefix}{next_arg.strip()}"
    git_head = resolved_git_head_branch(logical)
    pr_base = constants.env_or_default("RBC_PR_BASE", constants.MAIN_BRANCH)

    if not git_head.strip() or git_head == constants.MAIN_BRANCH:
        print("ERROR: bad feature branch name — adjust RBC_MAIN_HEAD_PREFIX / RBC_BRANCH_*")
        sys.exit(1)

    print("--- Plan (add-only) ---")
    print(f"  Catalog:  copy {old.catalog_dir}/  →  {new.catalog_dir}/  (contents unchanged)")
    print(f"  Tekton:   new files from templates {old.tekton_seg}  →  {new.tekton_seg}")
    print(f"  rhoai-version: {target_rhoai_version_value(new)!r}")
    print(f"  Branch: {git_head!r}  (base {pr_base!r})")

    repo_dir = MAIN_REPO.rstrip("/").split("/")[-1].replace(".git", "")
    clone_repo(repo_dir)
    os.chdir(repo_dir)
    setup_origin()
    assert_origin_is_main_repo()
    print("\norigin (RBC_MAIN_REPO) =", MAIN_REPO, "| PR will merge into base branch:", pr_base)

    checkout_tracking_main()
    new_branch(git_head)

    step_copy_catalog_only(old, new)
    trig = step_force_trigger(new)
    tekton_paths = step_write_new_tekton_copies(old, new)

    stage = [os.path.join(CATALOG_DIR, new.catalog_dir)] + tekton_paths
    if trig:
        stage.append(trig)

    if dry:
        show_working_tree_changes()
        print("\nDry run complete — no commit, push, or GitHub PR.")
        return

    commit_and_push(
        git_head, list(dict.fromkeys(stage)), rebase_onto_base=pr_base
    )

    ensure_pr_base_on_origin(pr_base)
    open_pr(git_head, pr_base, prev_arg, next_arg)


if __name__ == "__main__":
    main()
