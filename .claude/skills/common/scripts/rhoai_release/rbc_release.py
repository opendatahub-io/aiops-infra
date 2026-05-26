"""
RHOAI release-branch automation (``release.py``).

**What it does (short):** clones ``RBC_MAIN_REPO``, checks out the **previous** release branch (``argv[1]``), ensures the
**PR base** branch exists on ``origin``. If it is **missing**, it is created **only on the remote** (ref from
``origin/argv[1]`` → new branch name) — **same tree as the previous line** — while you **stay** checked out on
``argv[1]``. **Then** a **local** ``automation-…`` branch is created from that tip, edits are committed and **pushed**,
and a **GitHub PR** merges automation **into** the PR base (the base tip advances **after** merge). Tekton + bundle +
csv updates run on the automation branch only.
**Exit:** 0 on success; 1 on validation/git/API errors.

**Pipeline / CI:** Set ``GITHUB_TOKEN`` in the job environment. Keep ``RBC_GIT_USE_GITHUB_TOKEN=1`` (default) so HTTPS Git
uses the token (no interactive prompt). The script sets ``GIT_TERMINAL_PROMPT=0`` so Git **fails fast** instead of
hanging if auth is missing. If **rebase** fails in CI, set ``RBC_REBASE_ONTO_LATEST=0`` or resolve branch drift on the
remote first.

**Typical product order** for a minor (example 3.4): ``3.3`` GA → ``3.4`` ea1 → ``3.4`` ea2 → … → ``3.4`` GA,
then ``3.5`` ea1 → …  The script does not invent that order; it maps **previous_branch → logical next train** (``argv[2]``).

**argv** must follow **time** (or maturity): ``previous`` = the branch you are **leaving**; **``argv[2]``** is the
**logical** next release branch (e.g. ``rhoai-3.4``). By default the **PR base** branch name is **exactly** ``argv[2]``
(set ``RBC_STAGING_BRANCH_SUFFIX`` e.g. to ``-test`` only if you use a separate name like ``rhoai-3.4-test``). If
``argv[2]`` already ends with that suffix, logical train is derived by stripping it. Reversing argv order still corrupts
files. A progression check runs by default; set ``RBC_SKIP_PROGRESSION_CHECK=1`` to disable (e.g. hotfix flows).

**Repo / branches:** **Release lines only** — not ``main``. If the PR base branch is **missing** on ``origin``, it is
**created and pushed** at the **same commit as ``argv[1]``**. **Automation head** is ``automation-<train>``. **PR:**
merge **head → base**. ``argv[1]`` stays unchanged on the remote. Override PR base with ``RBC_PR_BASE`` if needed.

**Token:** ``GITHUB_TOKEN`` must be allowed to push branches and open pull requests on ``RBC_MAIN_REPO``. For HTTPS,
Git does not read ``.env`` by itself; when ``RBC_GIT_USE_GITHUB_TOKEN=1`` (default), the same token is embedded in
clone/remote URLs so ``git`` does not prompt. Set ``RBC_GIT_USE_GITHUB_TOKEN=0`` to use only the OS credential helper.

**Small PR:** New PR base branch (when created) matches ``argv[1]`` tip; diff stays small. Default
``RBC_REBASE_ONTO_LATEST=1`` rebases the automation branch onto the latest base before push (set ``0`` to skip). The
automation **commit** touches at most **six paths** — confirm with ``git show --stat``.

``--dry-run`` or ``RBC_DRY_RUN=1``: apply edits locally, then print git status + diff only (no commit, push, or PR),
same idea as ``src.cli`` dry-run + ``git_ops.show_changes``.

Run from repo root: ``python -m src.rbc_release ...``, or from ``src/``: ``python rbc_release.py ...`` (repo root on
``sys.path``). Loads ``.env`` from the repository root (secrets only there).
"""

from pathlib import Path

from dotenv import find_dotenv, load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")
_dotenv_found = find_dotenv()
if _dotenv_found:
    load_dotenv(_dotenv_found)

import glob
import os
import re
import shutil
import subprocess
import sys
from typing import Optional
from urllib.parse import quote

import requests

# ``python rbc_release.py`` from ``src/`` leaves ``__package__`` unset — need repo root for ``src.*`` imports.
if __package__ is None:
    _rp = str(_REPO_ROOT)
    if _rp not in sys.path:
        sys.path.insert(0, _rp)

import rbc_build_config_constants as constants

MAIN_REPO = constants.env_or_default("RBC_MAIN_REPO", constants.RBC_MAIN_REPO)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

TEKTON_DIR = constants.TEKTON_DIR
BUNDLE_PATCH = constants.BUNDLE_PATCH
CSV_PATCH = constants.CSV_PATCH


def dry_run_requested() -> bool:
    if "--dry-run" in sys.argv[1:]:
        return True
    v = constants.env_or_default("RBC_DRY_RUN", constants.RBC_DRY_RUN).strip().lower()
    return v in ("1", "true", "yes", "on")


def _strip_dry_run_argv() -> list[str]:
    return [a for a in sys.argv[1:] if a != "--dry-run"]


def show_working_tree_changes() -> None:
    """Print git status + diff (uses ``git_ops.show_changes`` when available)."""
    try:
        from src.git_ops import show_changes

        show_changes(Path.cwd())
    except Exception as e:
        print(f"(git_ops.show_changes unavailable: {e})")
        st = subprocess.run(
            ["git", "status"], capture_output=True, text=True, check=True
        ).stdout
        df = subprocess.run(
            ["git", "diff"], capture_output=True, text=True
        ).stdout
        print("--- git status ---\n", st, "\n--- git diff ---\n", df, sep="")


def resolved_git_latest_branch(logical_latest_branch):
    """
    Legacy PR-head naming (prefix + logical + suffix). ``main`` uses :func:`resolved_automation_head_branch` instead.
    """
    p = constants.env_or_default("RBC_BRANCH_PREFIX", constants.RBC_BRANCH_PREFIX)
    if "RBC_BRANCH_SUFFIX" in os.environ:
        s = os.environ["RBC_BRANCH_SUFFIX"]
    else:
        s = constants.RBC_BRANCH_SUFFIX
    return f"{p}{logical_latest_branch}{s}"


def logical_and_staging_branches(argv2: str) -> tuple[str, str]:
    """
    ``argv[2]`` is normally the **logical** train (e.g. ``rhoai-3.4``). PR base = logical + ``RBC_STAGING_BRANCH_SUFFIX``
    (default empty ⇒ base name equals ``argv[2]``). If ``argv[2]`` already ends with that suffix, treat as full base
    name and derive logical by stripping.
    """
    suf = constants.env_or_default(
        "RBC_STAGING_BRANCH_SUFFIX", constants.RBC_STAGING_BRANCH_SUFFIX
    ).strip()
    s = argv2.strip()
    if not suf:
        return s, s
    if len(s) >= len(suf) and s.lower().endswith(suf.lower()):
        return s[: -len(suf)], s
    return s, f"{s}{suf}"


def resolved_automation_head_branch(logical_latest: str) -> str:
    """
    PR head branch: ``RBC_AUTOMATION_BRANCH_PREFIX`` + train without a leading ``rhoai-`` (e.g. ``automation-3.4``).
    """
    p = constants.env_or_default(
        "RBC_AUTOMATION_BRANCH_PREFIX", constants.RBC_AUTOMATION_BRANCH_PREFIX
    )
    body = logical_latest.strip()
    m = re.match(r"^rhoai-", body, re.IGNORECASE)
    if m:
        body = body[len(m.group(0)) :]
    return f"{p}{body}"


def skip_ci_from_env():
    """Default: add [skip ci] to commits so pushes do not trigger nightly/build workflows."""
    v = constants.env_or_default("RBC_SKIP_CI", constants.RBC_SKIP_CI).strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def run(cmd):
    """Run a subprocess; inherits env (including ``GIT_TERMINAL_PROMPT`` set in :func:`main`)."""
    subprocess.run(cmd, check=True)


def _normalize_repo_url(url: str) -> str:
    u = (url or "").strip().rstrip("/").lower()
    u = u.replace("https://", "").replace("http://", "").replace(".git", "")
    # Strip credentials (token@host or user:pass@host) so token-embedded URLs compare equal to plain URLs.
    if "@" in u:
        u = u.split("@", 1)[1]
    return u.rstrip("/")


def _repo_url_identity(url: str) -> str:
    """Same repo as ``_normalize_repo_url`` but strips ``user@`` / ``token@`` before the host (for HTTPS with PAT)."""
    u = (url or "").strip().rstrip("/").lower()
    u = u.replace("https://", "").replace("http://", "").replace(".git", "")
    if "@" in u:
        u = u.split("@", 1)[-1]
    return u.rstrip("/")


def _git_https_url_with_github_token(url: str) -> str:
    """
    Embed ``GITHUB_TOKEN`` into ``https://github.com/...`` so ``git clone`` / ``fetch`` / ``push`` authenticate
    without a username/password prompt. Optional: set ``RBC_GIT_USE_GITHUB_TOKEN=0`` to disable.
    """
    u = (url or "").strip()
    if not u.startswith("https://github.com/"):
        return u
    v = constants.env_or_default(
        "RBC_GIT_USE_GITHUB_TOKEN", constants.RBC_GIT_USE_GITHUB_TOKEN
    ).strip().lower()
    if v in ("0", "false", "no", "off"):
        return u
    tok = (os.getenv("GITHUB_TOKEN") or "").strip()
    if not tok:
        return u
    rest = u[len("https://") :]
    if "@" in rest.split("/", 1)[0]:
        return u
    return f"https://{quote(tok, safe='')}@{rest}"


def push_to_origin(ref, *, force=False, force_with_lease=False):
    """Push to ``origin`` (must equal ``RBC_MAIN_REPO``)."""
    if force and force_with_lease:
        print("ERROR: push_to_origin: use only one of force= or force_with_lease=")
        sys.exit(1)
    assert_origin_is_main_repo()
    cmd = ["git", "push"]
    if force_with_lease:
        cmd.append("--force-with-lease")
    elif force:
        cmd.append("--force")
    cmd.extend(["origin", ref])
    run(cmd)


def clone_repo(repo_dir_name):
    if os.path.exists(repo_dir_name):
        shutil.rmtree(repo_dir_name)
    url = _git_https_url_with_github_token(MAIN_REPO)
    run(["git", "clone", url, repo_dir_name])


def setup_origin():
    """Point ``origin`` at ``RBC_MAIN_REPO`` (idempotent after ``git clone``)."""
    url = _git_https_url_with_github_token(MAIN_REPO)
    r = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        run(["git", "remote", "add", "origin", url])
    else:
        run(["git", "remote", "set-url", "origin", url])


def assert_origin_is_main_repo():
    """Sanity check: ``origin`` URL must match ``RBC_MAIN_REPO`` (the product GitHub repo, not “the main branch”)."""
    r = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=True,
    )
    origin_url = r.stdout.strip().rstrip("/")
    main = MAIN_REPO.strip().rstrip("/")
    if _repo_url_identity(origin_url) != _repo_url_identity(main):
        print(
            "ERROR: git remote origin must match RBC_MAIN_REPO for direct push/PR mode.\n"
            f"  origin: {origin_url!r}\n"
            f"  RBC_MAIN_REPO: {main!r}"
        )
        sys.exit(1)


def try_fetch_branch(remote, branch):
    """Fetch only `branch` from `remote` into refs/remotes/{remote}/{branch}."""
    r = subprocess.run(
        ["git", "fetch", remote, f"{branch}:refs/remotes/{remote}/{branch}"],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def have_remote_branch(remote, branch):
    r = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/remotes/{remote}/{branch}"],
        capture_output=True,
    )
    return r.returncode == 0


def _git_rev_parse(ref: str) -> str:
    """Resolve ``ref`` to a full commit SHA."""
    r = subprocess.run(
        ["git", "rev-parse", ref],
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout.strip()


def checkout_base_branch(base_branch):
    """
    Check out the previous release branch from ``origin`` (``RBC_MAIN_REPO``) so the new branch matches
    product history.
    """
    if try_fetch_branch("origin", base_branch) and have_remote_branch(
        "origin", base_branch
    ):
        run(["git", "checkout", "-B", base_branch, f"origin/{base_branch}"])
        print(f"Checked out {base_branch!r} from origin.")
        return

    print(
        f"ERROR: Could not fetch {base_branch!r} from origin ({MAIN_REPO}). "
        "Check the branch name exists on the remote."
    )
    sys.exit(1)


def create_new_branch(branch_name):
    run(["git", "checkout", "-B", branch_name])


def checkout_and_publish_staging_branch_for_pr(
    previous_branch: str, staging_branch: str, dry_run: bool = False
) -> None:
    """
    If the PR base branch (``staging_branch`` = ``argv[2]`` + suffix) is missing on ``origin``, publish it **only on the
    remote** using a refspec — **same commit as** ``origin/previous_branch`` (the previous line’s tree). We **do not**
    check out the PR base locally; you stay on ``previous_branch`` so the next step can create the **automation**
    branch from that tip only.

    If ``staging_branch`` already exists on ``origin``, skip.

    In dry-run mode, skip the actual push operation.
    """

    if branch_exists_on_origin(staging_branch):
        print(
            f"NOTE: {staging_branch!r} already on origin — skipping PR-base create/push; "
            f"automation still builds from {previous_branch!r} only."
        )
        return

    head_sha = _git_rev_parse("HEAD")
    tip_previous = _git_rev_parse(f"origin/{previous_branch}")
    if head_sha != tip_previous:
        print(
            f"ERROR: local HEAD ({head_sha[:12]}) must match origin/{previous_branch} ({tip_previous[:12]}). "
            "You must be checked out on the previous release line before publishing the PR base."
        )
        sys.exit(1)

    if dry_run:
        print(
            f"DRY RUN: Would push PR base {staging_branch!r} on origin at {tip_previous[:12]} — **identical** to "
            f"{previous_branch!r} (skipped in dry-run mode)."
        )
        return

    # Remote-only: new branch name at the same object as the previous line (no local checkout of PR base).
    run(
        [
            "git",
            "push",
            "origin",
            f"{tip_previous}:refs/heads/{staging_branch}",
        ]
    )
    print(
        f"Pushed PR base {staging_branch!r} on origin at {tip_previous[:12]} — **identical** to "
        f"{previous_branch!r}. Next: create local **automation** branch here, commit, push, and open PR."
    )


def branch_exists_on_origin(branch_name):
    r = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        capture_output=True,
        text=True,
    )
    return bool(r.stdout.strip())


def skip_pr_base_push() -> bool:
    """If true, do not push the PR base when it is missing on ``origin`` (error instead)."""
    return constants.env_or_default(
        "RBC_SKIP_PR_BASE_PUSH", constants.RBC_SKIP_PR_BASE_PUSH
    ).strip().lower() in (
        "1",
        "true",
        "yes",
    )


def ensure_pr_base_on_origin(base_branch, *, sync_when_default_base=True):
    """
    GitHub needs ``base`` to exist on the same repo as ``head``. On the product repo the base branch almost
    always already exists; if not, push the local branch **once** without ``--force`` (never overwrites an
    existing remote branch).

    ``RBC_SKIP_PR_BASE_PUSH``: if the base is missing on ``origin``, exit with an error instead of pushing.

    ``sync_when_default_base`` is kept for call-site compatibility; base is never force-updated on the product repo.
    """
    _ = sync_when_default_base
    r = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{base_branch}"],
        capture_output=True,
    )
    if r.returncode != 0:
        print(
            f"ERROR: PR base {base_branch!r} has no local refs/heads entry. "
            f"Set RBC_PR_BASE to a branch you have checked out, or fix checkout."
        )
        sys.exit(1)

    if branch_exists_on_origin(base_branch):
        return

    if skip_pr_base_push():
        print(
            f"ERROR: PR base {base_branch!r} is not on origin and RBC_SKIP_PR_BASE_PUSH is set "
            "— refusing to push base."
        )
        sys.exit(1)

    print(
        f"Pushing {base_branch!r} to origin once (branch missing on remote; no --force)."
    )
    push_to_origin(base_branch)


def ensure_local_branch_ref_from_origin(branch_name: str) -> None:
    """Ensure ``refs/heads/{branch}`` exists so ``git rev-parse`` / PR helpers work (no checkout)."""
    r = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        capture_output=True,
    )
    if r.returncode == 0:
        return
    if not branch_exists_on_origin(branch_name):
        print(
            f"ERROR: need local ref for {branch_name!r} but branch is missing on origin."
        )
        sys.exit(1)
    if not try_fetch_branch("origin", branch_name) or not have_remote_branch(
        "origin", branch_name
    ):
        print(f"ERROR: could not fetch {branch_name!r} from origin.")
        sys.exit(1)
    run(["git", "branch", "-f", branch_name, f"origin/{branch_name}"])


# ---------------- VERSION HELPERS ---------------- #


def extract_parts(text):
    match = re.search(r"(\d+)[.-](\d+)", text)
    if not match:
        print("ERROR: Cannot extract major.minor from:", text)
        sys.exit(1)
    return match.groups()


def is_ea_release_branch(branch_name):
    """True for EA drops (rhoai-x.y.ea-1, rhoai-x.y-ea-2, etc.)."""
    if re.search(r"\bea[\.\-]?\d+", branch_name, re.IGNORECASE):
        return True
    return "ea" in branch_name.lower()


def get_ea_suffix(branch_name):
    match = re.search(r"ea[\.\-]?\d+", branch_name, re.IGNORECASE)
    return match.group(0) if match else None


def validate_chronological_release_pair(
    previous_branch,
    latest_branch,
    om,
    on,
    nm,
    nn,
    prev_is_ea,
    prev_ea,
    latest_is_ea,
    new_ea,
):
    """
    Reject obvious mistakes: older major.minor as ``latest``, same GA→GA, or non-increasing EA on same x.y.
    Set ``RBC_SKIP_PROGRESSION_CHECK=1`` to skip.
    """
    if constants.env_or_default(
        "RBC_SKIP_PROGRESSION_CHECK", constants.RBC_SKIP_PROGRESSION_CHECK
    ).strip().lower() in ("1", "true", "yes"):
        return
    omi, oni, nmi, nni = int(om), int(on), int(nm), int(nn)
    if (nmi, nni) < (omi, oni):
        print(
            "ERROR: `latest_branch` has a lower major.minor than `previous_branch`.\n"
            f"  previous={previous_branch!r}  latest={latest_branch!r}\n"
            "Use chronological argv: (1) branch you are leaving, (2) next step — e.g.\n"
            "  rhoai-3.3 → rhoai-3.4.ea.1,  rhoai-3.4.ea.1 → rhoai-3.4.ea.2,  rhoai-3.4.ea.2 → rhoai-3.4,  rhoai-3.4 → rhoai-3.5.ea.1\n"
            "Set RBC_SKIP_PROGRESSION_CHECK=1 to skip this check."
        )
        sys.exit(1)
    if (nmi, nni) > (omi, oni):
        return
    # Same major.minor: EA→EA must increase ea N; EA→GA ok; GA→EA ok; GA→GA duplicate.
    if not prev_is_ea and not latest_is_ea:
        print(
            f"ERROR: both branches look like GA for {om}.{on} — duplicate train.\n"
            f"  previous={previous_branch!r}  latest={latest_branch!r}"
        )
        sys.exit(1)
    if prev_is_ea and not latest_is_ea:
        return
    if not prev_is_ea and latest_is_ea:
        return
    pin = _ea_num(prev_ea) if prev_ea else None
    nin = _ea_num(new_ea) if new_ea else None
    if pin is not None and nin is not None and int(nin) <= int(pin):
        print(
            f"ERROR: on train {om}.{on}, EA drop number must increase (was ea {pin}, latest has ea {nin}).\n"
            f"  previous={previous_branch!r}  latest={latest_branch!r}\n"
            "You may have swapped argv order (testing “in reverse”)."
        )
        sys.exit(1)


# ---------------- BUILD MAPPING ---------------- #
# Dotted train (3.4, 3.4.0) uses EA fragments ea.1 / ea.2
# Dashed train (3-4, 3-4-0) uses EA fragments ea-1 / ea-2 — never v3-4-ea.1 for dashed.


def _ea_num(ea_raw):
    m = re.match(r"ea[.\-]?(\d+)", ea_raw, re.IGNORECASE)
    return m.group(1) if m else None


def _ea_dotted_pairs(old_ea_raw, new_ea_raw):
    """EA -> EA for dotted major.minor only: ea.N with a dot."""
    oi = _ea_num(old_ea_raw)
    ni = _ea_num(new_ea_raw)
    if oi is None or ni is None:
        return [(old_ea_raw, new_ea_raw)]
    return [
        (f"ea.{oi}", f"ea.{ni}"),
        (f"EA.{oi}", f"EA.{ni}"),
    ]


def _ea_dashed_pairs(old_ea_raw, new_ea_raw):
    """EA -> EA for dashed major-minor only: ea-N with a hyphen."""
    oi = _ea_num(old_ea_raw)
    ni = _ea_num(new_ea_raw)
    if oi is None or ni is None:
        return [(old_ea_raw, new_ea_raw)]
    return [
        (f"ea-{oi}", f"ea-{ni}"),
        (f"EA-{oi}", f"EA-{ni}"),
    ]


def build_expanded_mapping(
    old_major,
    old_minor,
    new_major,
    new_minor,
    prev_ea,
    new_ea,
):
    """
    Full old_string -> new_string map for replace_all (longest keys handled by caller).
    Covers dot/dash major.minor, optional .0 / -0, and EA suffixes in parallel forms.
    """
    om, on, nm, nn = old_major, old_minor, new_major, new_minor
    pairs = []

    def add(o, n):
        if o and n and o != n:
            pairs.append((o, n))

    pe, ne = prev_ea, new_ea

    if not pe and not ne:
        # GA -> GA
        add(f"{om}.{on}", f"{nm}.{nn}")
        add(f"{om}-{on}", f"{nm}-{nn}")
        add(f"{om}.{on}.0", f"{nm}.{nn}.0")
        add(f"{om}-{on}-0", f"{nm}-{nn}-0")
    elif not pe and ne:
        # GA -> EA: dotted lines get ea.{n}, dashed lines get ea-{n}
        n = _ea_num(ne)
        if n:
            add(f"{om}.{on}", f"{nm}.{nn}-ea.{n}")
            add(f"{om}.{on}.0", f"{nm}.{nn}.0-ea.{n}")
            add(f"{om}-{on}", f"{nm}-{nn}-ea-{n}")
            add(f"{om}-{on}-0", f"{nm}-{nn}-0-ea-{n}")
        else:
            add(f"{om}.{on}", f"{nm}.{nn}-{ne}")
            add(f"{om}-{on}", f"{nm}-{nn}-{ne}")
    elif pe and ne:
        # EA -> EA: dotted train vs dashed train separately (no v3-4-ea.1)
        for o_frag, n_frag in _ea_dotted_pairs(pe, ne):
            add(f"{om}.{on}-{o_frag}", f"{nm}.{nn}-{n_frag}")
            add(f"{om}.{on}.0-{o_frag}", f"{nm}.{nn}.0-{n_frag}")
        for o_frag, n_frag in _ea_dashed_pairs(pe, ne):
            add(f"{om}-{on}-{o_frag}", f"{nm}-{nn}-{n_frag}")
            add(f"{om}-{on}-0-{o_frag}", f"{nm}-{nn}-0-{n_frag}")
    elif pe and not ne:
        # EA -> GA: strip EA fragments; also bump plain x.y / x.y.0 (csv often keeps "3.4" with no EA text)
        n = _ea_num(pe)
        if n:
            for suf in (f"ea.{n}", f"EA.{n}"):
                add(f"{om}.{on}-{suf}", f"{nm}.{nn}")
                add(f"{om}.{on}.0-{suf}", f"{nm}.{nn}.0")
            for suf in (f"ea-{n}", f"EA-{n}"):
                add(f"{om}-{on}-{suf}", f"{nm}-{nn}")
                add(f"{om}-{on}-0-{suf}", f"{nm}-{nn}-0")
        else:
            for o_frag in (pe,):
                add(f"{om}.{on}-{o_frag}", f"{nm}.{nn}")
                add(f"{om}-{on}-{o_frag}", f"{nm}-{nn}")
        # Same as GA->GA when minor/major changes (e.g. 3.4 EA -> 3.5 GA); skipped when om/on == nm/nn
        add(f"{om}.{on}", f"{nm}.{nn}")
        add(f"{om}-{on}", f"{nm}-{nn}")
        add(f"{om}.{on}.0", f"{nm}.{nn}.0")
        add(f"{om}-{on}-0", f"{nm}-{nn}-0")

    # Tekton file names use v{maj}-{min} or v{maj}.{min} — same dotted vs dashed rules as content.
    # Include v-prefixed strings so renames match bundle/CI paths (e.g. v3-4-ea-1, not v3-4-ea.1).
    _add_tekton_v_prefix_mapping(add, om, on, nm, nn, pe, ne)

    # Deduplicate: same old key keeps first new (should not diverge)
    out = {}
    for o, n in pairs:
        out.setdefault(o, n)
    return out


def _add_tekton_v_prefix_mapping(add, om, on, nm, nn, pe, ne):
    """Extra keys for v3-4 / v3.4 style segments in Tekton *filenames* (and YAML refs)."""
    oi = _ea_num(pe) if pe else None
    ni = _ea_num(ne) if ne else None

    if not pe and not ne:
        add(f"v{om}-{on}", f"v{nm}-{nn}")
        add(f"v{om}.{on}", f"v{nm}.{nn}")
        add(f"v{om}-{on}-0", f"v{nm}-{nn}-0")
        add(f"v{om}.{on}.0", f"v{nm}.{nn}.0")
    elif not pe and ne and ni:
        add(f"v{om}-{on}", f"v{nm}-{nn}-ea-{ni}")
        add(f"v{om}-{on}-0", f"v{nm}-{nn}-0-ea-{ni}")
        add(f"v{om}.{on}", f"v{nm}.{nn}-ea.{ni}")
        add(f"v{om}.{on}.0", f"v{nm}.{nn}.0-ea.{ni}")
        add(f"v{om}-{on}-ea.{ni}", f"v{nm}-{nn}-ea-{ni}")
    elif pe and ne and oi and ni:
        for o_frag, n_frag in _ea_dotted_pairs(pe, ne):
            add(f"v{om}.{on}-{o_frag}", f"v{nm}.{nn}-{n_frag}")
            add(f"v{om}.{on}.0-{o_frag}", f"v{nm}.{nn}.0-{n_frag}")
        for o_frag, n_frag in _ea_dashed_pairs(pe, ne):
            add(f"v{om}-{on}-{o_frag}", f"v{nm}-{nn}-{n_frag}")
            add(f"v{om}-{on}-0-{o_frag}", f"v{nm}-{nn}-0-{n_frag}")
        add(f"v{om}-{on}-ea.{oi}", f"v{nm}-{nn}-ea-{ni}")
        add(f"v{om}.{on}-ea-{oi}", f"v{nm}.{nn}-ea.{ni}")
    elif pe and not ne and oi:
        for suf in (f"ea.{oi}", f"EA.{oi}"):
            add(f"v{om}.{on}-{suf}", f"v{nm}.{nn}")
            add(f"v{om}.{on}.0-{suf}", f"v{nm}.{nn}.0")
        for suf in (f"ea-{oi}", f"EA-{oi}"):
            add(f"v{om}-{on}-{suf}", f"v{nm}-{nn}")
            add(f"v{om}-{on}-0-{suf}", f"v{nm}-{nn}-0")
        add(f"v{om}-{on}", f"v{nm}-{nn}")
        add(f"v{om}.{on}", f"v{nm}.{nn}")
        add(f"v{om}-{on}-0", f"v{nm}-{nn}-0")
        add(f"v{om}.{on}.0", f"v{nm}.{nn}.0")


# ---------------- SAFE REPLACE ---------------- #


def replace_all(text, mapping):
    temp_map = {}
    for i, old in enumerate(sorted(mapping.keys(), key=len, reverse=True)):
        token = f"__TMP{i}__"
        temp_map[token] = mapping[old]
        text = text.replace(old, token)

    for token, new_val in temp_map.items():
        text = text.replace(token, new_val)

    return text


# docs.redhat.com uses the parent documentation train (x.y) only — never x.y-ea.n in the path.
_RHOAI_SELF_MANAGED_DOCS_PREFIX = "red_hat_openshift_ai_self-managed/"


def normalize_self_managed_docs_url_version(text):
    """
    After generic version replace_all, docs links can wrongly become ``.../3.5-ea.1``; Red Hat expects
    ``.../3.5`` (same as GA lines like ``.../3.4``). Strip EA suffixes only after this path prefix.
    """
    p = re.escape(_RHOAI_SELF_MANAGED_DOCS_PREFIX)
    for pat, repl in (
        (rf"({p})(\d+\.\d+)-ea\.\d+", r"\1\2"),
        (rf"({p})(\d+\.\d+)-ea-\d+", r"\1\2"),
        (rf"({p})(\d+\.\d+)\.ea\.\d+", r"\1\2"),
    ):
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    return text


def replace_tekton_yaml_content(text, mapping):
    """
    Like bundle-patch: only touch lines that actually contain a version token we replace.
    Unchanged lines stay byte-identical (avoids “whole file” diffs from touching every line).
    """
    keys = sorted(mapping.keys(), key=len, reverse=True)
    out = []
    for line in text.splitlines(keepends=True):
        if any(k in line for k in keys):
            out.append(replace_all(line, mapping))
        else:
            out.append(line)
    return "".join(out)


# ---------------- FILE UPDATES ---------------- #
# Eight Tekton files (four stems × push/scheduled) + bundle-patch + csv-patch (csv skipped for same-train EA→EA).
# Renames use the same mapping as content, including v3-4 / v3.4 filename segments.


TEKTON_RELEASE_STEMS = (
    "odh-operator-bundle",
    "rhoai-fbc-fragment",
    "rhai-on-openshift-chart",
    "rhai-on-xks-chart",
)


def resolve_tekton_release_paths(major, minor):
    """
    RBC Tekton YAMLs for this checkout: ``{stem}-v{maj}-{min}`` or ``{stem}-v{maj}-{min}-ea-*`` × push/scheduled.
    """
    if not os.path.isdir(TEKTON_DIR):
        print(f"ERROR: missing {TEKTON_DIR}/")
        sys.exit(1)

    paths = []
    for stem in TEKTON_RELEASE_STEMS:
        for kind in ("push", "scheduled"):
            exact = os.path.join(TEKTON_DIR, f"{stem}-v{major}-{minor}-{kind}.yaml")
            if os.path.isfile(exact):
                paths.append(exact)
                continue
            pat = os.path.join(TEKTON_DIR, f"{stem}-v{major}-{minor}*-{kind}.yaml")
            matches = sorted(glob.glob(pat))
            if len(matches) != 1:
                print(
                    f"ERROR: expected exactly one Tekton file for {stem} ({kind}), "
                    f"pattern {pat!r}, got {matches}"
                )
                sys.exit(1)
            paths.append(matches[0])
    return paths


def update_tekton_files(mapping, paths):
    """
    Rename + rewrite content only for the given paths. Returns final paths after renames.

    Renames use ``git mv``. Content uses line-targeted replacement: only lines containing a
    mapped version substring are edited (same idea as bundle: only version-ish lines change).
    """
    final = []
    for old_path in paths:
        directory, base = os.path.split(old_path)
        new_base = replace_all(base, mapping)
        new_path = os.path.join(directory, new_base)
        if old_path != new_path:
            run(["git", "mv", old_path, new_path])
        target = new_path
        with open(target, encoding="utf-8", newline="") as f:
            content = f.read()
        content = replace_tekton_yaml_content(content, mapping)
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        final.append(target)
    return final


def update_bundle_patch(mapping):
    if not os.path.exists(BUNDLE_PATCH):
        return

    with open(BUNDLE_PATCH, encoding="utf-8", newline="") as f:
        content = f.read()

    content = replace_all(content, mapping)
    content = normalize_self_managed_docs_url_version(content)

    with open(BUNDLE_PATCH, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def update_csv_patch(mapping, skip_for_ea_train):
    if not os.path.exists(CSV_PATCH):
        return

    if skip_for_ea_train:
        print(
            "Skipping csv-patch: EA latest on the *same* x.y train as previous — CSV keeps "
            "major.minor (e.g. 3.4 for rhoai-3.4.ea-*). When x.y bumps (e.g. 3.4 EA → 3.5), "
            "csv is edited."
        )
        return

    with open(CSV_PATCH, encoding="utf-8", newline="") as f:
        content = f.read()

    content = replace_all(content, mapping)
    content = normalize_self_managed_docs_url_version(content)

    with open(CSV_PATCH, "w", encoding="utf-8", newline="") as f:
        f.write(content)


# ---------------- GIT ---------------- #


def rebase_onto_latest_enabled() -> bool:
    """When True (default), rebase automation branch onto latest PR base tip before push."""
    v = constants.env_or_default(
        "RBC_REBASE_ONTO_LATEST", constants.RBC_REBASE_ONTO_LATEST
    ).strip().lower()
    return v not in ("0", "false", "no", "off", "")


def commit_and_push(
    branch_name, paths_to_stage, *, rebase_onto_latest: Optional[str] = None
):
    """Stage only listed paths. Optionally rebase onto ``origin/<rebase_onto_latest>`` before push (small GitHub PR)."""
    existing = [p for p in paths_to_stage if os.path.isfile(p)]
    if not existing:
        print(
            "ERROR: None of the expected paths exist to stage (Tekton YAMLs, bundle/csv)."
        )
        sys.exit(1)

    run(["git", "add", "--"] + existing)

    cached = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().splitlines()
    print(
        f"\n--- Automation will commit {len(cached)} path(s) (expect ≤10: Tekton + bundle [+ csv]) ---"
    )
    for p in cached:
        print(f"  {p}")
    max_staged = int(
        constants.env_or_default(
            "RBC_MAX_STAGED_PATHS", constants.RBC_MAX_STAGED_PATHS
        ).strip()
        or "20"
    )
    if len(cached) > max_staged:
        print(
            f"ERROR: staged {len(cached)} paths (limit RBC_MAX_STAGED_PATHS={max_staged}). "
            "This script should only touch a handful of YAMLs — aborting so nothing huge is committed."
        )
        sys.exit(1)

    st = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    committed = False
    if not st.stdout.strip():
        print("Nothing to commit; skipping commit.")
    else:
        msg = f"Automation {branch_name}"
        if skip_ci_from_env():
            msg += " [skip ci]"
        run(["git", "commit", "-m", msg])
        committed = True

    if (
        committed
        and rebase_onto_latest
        and rebase_onto_latest_enabled()
    ):
        if not try_fetch_branch("origin", rebase_onto_latest) or not have_remote_branch(
            "origin", rebase_onto_latest
        ):
            print(
                f"ERROR: cannot fetch origin/{rebase_onto_latest} for rebase. "
                "Set RBC_REBASE_ONTO_LATEST=0 to skip rebase."
            )
            sys.exit(1)
        print(
            f"\nRebasing onto origin/{rebase_onto_latest} so the GitHub PR shows only the automation "
            "diff (not unrelated history). Set RBC_REBASE_ONTO_LATEST=0 to skip.\n"
        )
        try:
            run(["git", "rebase", f"origin/{rebase_onto_latest}"])
        except subprocess.CalledProcessError as e:
            print(
                "ERROR: git rebase failed — fix conflicts and continue, or set RBC_REBASE_ONTO_LATEST=0 "
                "to push without rebase (GitHub PR will list many files).",
                e,
            )
            sys.exit(1)
        push_to_origin(branch_name, force_with_lease=True)
    else:
        push_to_origin(branch_name, force=True)


# ---------------- PR ---------------- #


def github_pr_target_repo():
    """``owner/repo`` for GitHub pull-requests API (from ``RBC_MAIN_REPO``)."""
    part = MAIN_REPO.split("github.com/", 1)[1]
    return part.replace(".git", "").strip("/")


def create_pr(head_branch, base_branch):
    """head = automation branch (commits); base = merge target (default: logical ``argv[2]`` + staging suffix). Not swapped."""
    if head_branch == base_branch:
        print(
            "ERROR: PR head and base are the same branch — GitHub will not create a usable PR. "
            "Use a different staging/automation branch pair or set RBC_PR_BASE."
        )
        sys.exit(1)

    repo = github_pr_target_repo()
    print(
        f"Opening release PR on {repo}: head={head_branch!r} base={base_branch!r} "
        "(release-line branches; not the default main-branch onboarding flow)"
    )
    url = f"https://api.github.com/repos/{repo}/pulls"
    compare_web = (
        f"https://github.com/{repo}/compare/"
        f"{quote(base_branch, safe='')}"
        f"..."
        f"{quote(head_branch, safe='')}"
    )

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = {
        "title": f"RHOAI release config: {head_branch} → {base_branch}",
        "head": head_branch,
        "base": base_branch,
        "body": (
            "## Summary\n\n"
            "Automated updates for the release line: merge changes from the automation branch into the target "
            "release branch.\n\n"
            "## Branches\n\n"
            f"- **Target:** `{base_branch}`\n"
            f"- **Source:** `{head_branch}`\n\n"
            "## Changes\n\n"
            "Release-line configuration only (not `main`): Tekton definitions under `.tekton`, "
            "`bundle/bundle-patch.yaml`, and `bundle/csv-patch.yaml` when applicable for this release step.\n\n"
            "## Review\n\n"
            "Please verify image references and bundle metadata for the intended release.\n\n"
            f"[View diff (compare)]({compare_web})"
        ),
    }

    r = requests.post(url, headers=headers, json=payload, timeout=120)
    try:
        r.raise_for_status()
    except requests.HTTPError:
        print("ERROR: GitHub API:", r.status_code, r.text)
        if r.status_code == 422 and "base" in r.text.lower():
            print(
                "Hint: `base` must exist on `origin` (same repo as `head`). "
                "Use an existing **release** branch name, or set RBC_PR_BASE to the branch you want as PR base."
            )
        sys.exit(1)
    data = r.json()
    url_pr = data.get("html_url", "")
    state = data.get("state")
    merged = data.get("merged")
    print("PR:", url_pr, "| state:", state, "| merged:", merged)
    print(
        "PR direction:  OLD (base) = {!r}  →  NEW (head) = {!r}".format(base_branch, head_branch)
    )
    print("Same diff as Compare:", compare_web)
    if state == "closed":
        print(
            "NOTE: PR is already closed. Common causes: duplicate PR merged earlier, "
            "base/head missing on origin, or an empty diff (same commit on head and base). "
            "Ensure both branches exist on the remote and RBC_PR_BASE points at a branch "
            "that differs from the head commit."
        )


# ---------------- MAIN ---------------- #


def main():
    # CI / pipelines: never block waiting for a TTY password prompt; fail the step instead of hanging.
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")

    if not (os.getenv("GITHUB_TOKEN") or "").strip():
        print("ERROR: GITHUB_TOKEN not set (set in environment or `.env` for local runs)")
        sys.exit(1)

    pos = _strip_dry_run_argv()
    if len(pos) != 2:
        print(
            "Usage: python -m src.rbc_release <previous_branch> <logical_next_branch> [--dry-run]\n"
            "  previous              = branch you leave (e.g. rhoai-3.3)\n"
            "  logical_next_branch   = next release line name only (e.g. rhoai-3.4).\n"
            "                          PR base branch = this + RBC_STAGING_BRANCH_SUFFIX (default: empty ⇒ same as argv[2]).\n"
            "  Automation PR head: RBC_AUTOMATION_BRANCH_PREFIX + train without rhoai- (e.g. automation-3.4).\n"
            "  --dry-run             Show git status + diff after edits; no commit, push, or PR (or set RBC_DRY_RUN=1).\n"
            "  Examples: rhoai-3.3 rhoai-3.4  |  rhoai-3.4.ea.1 rhoai-3.4.ea.2"
        )
        sys.exit(1)

    dry = dry_run_requested()
    previous_branch = pos[0]
    argv2 = pos[1]
    logical_latest, staging_branch = logical_and_staging_branches(argv2)
    if staging_branch != logical_latest:
        if argv2.strip() == staging_branch:
            print(
                f"NOTE: argv[2]={argv2!r} already ends with RBC_STAGING_BRANCH_SUFFIX — "
                f"logical train {logical_latest!r}, staging {staging_branch!r}."
            )
        else:
            print(
                f"NOTE: argv[2]={argv2!r} → logical {logical_latest!r}, staging PR base {staging_branch!r} "
                f"(appended RBC_STAGING_BRANCH_SUFFIX)."
            )

    old_major, old_minor = extract_parts(previous_branch)
    new_major, new_minor = extract_parts(logical_latest)

    latest_is_ea = is_ea_release_branch(logical_latest)
    new_ea = get_ea_suffix(logical_latest) if latest_is_ea else None
    if latest_is_ea and not new_ea:
        print("ERROR: EA branch name but could not parse ea suffix (e.g. ea-1, ea.1)")
        sys.exit(1)

    prev_is_ea = is_ea_release_branch(previous_branch)
    prev_ea = get_ea_suffix(previous_branch) if prev_is_ea else None
    if prev_is_ea and not prev_ea:
        print("ERROR: previous branch looks like EA but could not parse ea suffix")
        sys.exit(1)

    validate_chronological_release_pair(
        previous_branch,
        logical_latest,
        old_major,
        old_minor,
        new_major,
        new_minor,
        prev_is_ea,
        prev_ea,
        latest_is_ea,
        new_ea,
    )

    mapping = build_expanded_mapping(
        old_major,
        old_minor,
        new_major,
        new_minor,
        prev_ea,
        new_ea,
    )

    same_release_train = old_major == new_major and old_minor == new_minor
    # Skip csv when *latest* is still EA on the same x.y (e.g. ea1→ea2). When latest is GA or x.y changes, edit csv.
    skip_csv_same_train_ea = latest_is_ea and same_release_train

    # PR: default base = staging (logical + suffix); head = automation-* derived from logical_latest.
    pr_base = constants.env_or_default("RBC_PR_BASE", staging_branch)
    if pr_base != staging_branch:
        print(
            f"NOTE: RBC_PR_BASE={pr_base!r} (default staging merge target={staging_branch!r}) — "
            "merge target is overridden."
        )

    automation_branch = resolved_automation_head_branch(logical_latest)
    if not automation_branch.strip():
        print("ERROR: RBC_AUTOMATION_BRANCH_PREFIX produced an empty branch name.")
        sys.exit(1)
    if automation_branch == previous_branch:
        print(
            f"ERROR: automation branch name {automation_branch!r} equals previous_branch — "
            "adjust RBC_AUTOMATION_BRANCH_PREFIX or argv."
        )
        sys.exit(1)
    if automation_branch == staging_branch:
        print(
            f"ERROR: automation branch {automation_branch!r} equals staging branch {staging_branch!r} — "
            "PR head and base must differ (try a non-empty RBC_STAGING_BRANCH_SUFFIX or different prefix)."
        )
        sys.exit(1)
    if automation_branch == logical_latest:
        print(
            f"ERROR: automation branch {automation_branch!r} equals logical train {logical_latest!r} — "
            "use a distinct automation prefix."
        )
        sys.exit(1)
    print(
        f"NOTE: PR head branch {automation_branch!r} (logical train {logical_latest!r}, staging base {staging_branch!r})."
    )

    repo_dir = MAIN_REPO.rstrip("/").split("/")[-1].replace(".git", "")

    clone_repo(repo_dir)
    os.chdir(repo_dir)

    setup_origin()
    assert_origin_is_main_repo()
    # 1) Previous line on disk, then PR base branch on origin only (same commit as argv[1]); stay on argv[1].
    checkout_base_branch(previous_branch)
    checkout_and_publish_staging_branch_for_pr(previous_branch, staging_branch, dry_run=dry)
    # 2) Local automation branch from previous tip — commits and push go here only.
    create_new_branch(automation_branch)

    tekton_paths = resolve_tekton_release_paths(old_major, old_minor)
    tekton_final = update_tekton_files(mapping, tekton_paths)
    update_bundle_patch(mapping)
    update_csv_patch(mapping, skip_for_ea_train=skip_csv_same_train_ea)

    stage_paths = list(tekton_final)
    if os.path.isfile(BUNDLE_PATCH):
        stage_paths.append(BUNDLE_PATCH)
    if not skip_csv_same_train_ea and os.path.isfile(CSV_PATCH):
        stage_paths.append(CSV_PATCH)
    stage_paths = list(dict.fromkeys(stage_paths))

    if dry:
        show_working_tree_changes()
        print("\nDry run complete — no commit, push, or GitHub PR.")
        return

    commit_and_push(
        automation_branch, stage_paths, rebase_onto_latest=staging_branch
    )

    ensure_local_branch_ref_from_origin(pr_base)
    try_fetch_branch("origin", pr_base)
    rb = subprocess.run(
        ["git", "rev-parse", f"refs/remotes/origin/{pr_base}"],
        capture_output=True,
        text=True,
    )
    if rb.returncode != 0:
        print(f"ERROR: could not resolve origin/{pr_base} for PR check.")
        sys.exit(1)
    remote_base_sha = rb.stdout.strip()
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if remote_base_sha == head_sha:
        print(
            f"Skipping PR: automation tip matches origin/{pr_base} (no commits to merge). "
            "Previous branch was not modified. If the new line already matches automation on the remote, "
            "nothing to do; otherwise check previous / staging / logical train argv and that edits apply from the previous branch."
        )
        return

    print(
        "\n--- PR summary (release branches only; not `main`) ---\n"
        f"  Previous release branch (argv[1], checkout only): {previous_branch}\n"
        f"  argv[2] (logical next line): {argv2}\n"
        f"  Staging PR base (default merge target): {staging_branch}\n"
        f"  Logical train (mapping): {logical_latest}\n"
        f"  Automation branch (PR head, pushed): {automation_branch}\n"
        f"  GitHub PR base (override: RBC_PR_BASE): {pr_base}\n"
        "  Merge applies automation **onto** PR base (staging), not onto argv[1].\n"
        "  Expect a **small** diff: staged Tekton + bundle (+ csv when not skipped).\n"
    )
    ensure_pr_base_on_origin(
        pr_base, sync_when_default_base=(pr_base == staging_branch)
    )
    create_pr(automation_branch, pr_base)


if __name__ == "__main__":
    main()
