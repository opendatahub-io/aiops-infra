"""Shared fixtures for aiops-infra tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Ensure scripts/ and skill script directories are importable ──────────

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _add_skill_scripts(skill_name: str) -> None:
    """Add a skill's scripts/ directory to sys.path for testing."""
    skill_scripts = REPO_ROOT / "skills" / skill_name / "scripts"
    if skill_scripts.is_dir() and str(skill_scripts) not in sys.path:
        sys.path.insert(0, str(skill_scripts))


_add_skill_scripts("conforma-analyze")
_add_skill_scripts("conforma-exception")
_add_skill_scripts("conforma-report-fetch")


# ── Shared fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def tmp_csv(tmp_path):
    """Create a temporary CSV file with sample violation data."""
    csv_content = (
        "type,component_name,image,message,effective_on,code,title,description,solution\n"
        'violation,odh-model-server-v3-4,quay.io/img:sha,"Task is not hermetic",2026-01-01,'
        'hermetic_task.hermetic,Hermetic build required,Must be hermetic,Enable hermetic builds\n'
        'violation,odh-modelmesh-v3-4,quay.io/img2:sha,"Task ""prefetch-dependencies"" '
        'is not trusted",2026-01-01,trusted_task.trusted,Task must be trusted,'
        "Untrusted task,Upgrade task\n"
        'warning,odh-other-v3-4,quay.io/img3:sha,"Minor issue",2026-01-01,'
        "some_warning.code,Warning title,Warning desc,Fix it\n"
        'violation,odh-vllm-v3-4,quay.io/img4:sha,"RPM not signed with allowed key '
        '1234567890abcdef",2026-02-01,rpm_signature.allowed,RPM signing required,'
        "RPMs must be signed,Sign RPMs\n"
    )
    csv_file = tmp_path / "rhoai-3.4.csv"
    csv_file.write_text(csv_content)
    return csv_file


@pytest.fixture
def tmp_reports_dir(tmp_csv):
    """A directory containing the sample CSV (named as a release)."""
    return tmp_csv.parent
