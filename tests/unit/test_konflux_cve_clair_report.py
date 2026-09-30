"""Parser tests for Konflux Clair report JSON."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "konflux-cve-scan-analyze"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import clair_report  # noqa: E402
import analyze_cve_report  # noqa: E402


CLAIR_V4 = {
    "manifest_hash": "sha256:abc",
    "packages": {
        "1": {"id": "1", "name": "axios", "version": "1.6.0", "kind": "npm"},
        "2": {"id": "2", "name": "rsync", "version": "3.2.7-1.el9", "kind": "binary"},
    },
    "vulnerabilities": {
        "CVE-2026-42044": {
            "id": "CVE-2026-42044",
            "name": "CVE-2026-42044",
            "severity": "High",
            "fixed_in_version": "1.7.0",
        },
        "CVE-2026-10001": {
            "id": "CVE-2026-10001",
            "name": "CVE-2026-10001",
            "severity": "High",
            "fixed_in_version": "",
        },
    },
    "package_vulnerabilities": {
        "1": ["CVE-2026-42044"],
        "2": ["CVE-2026-10001"],
    },
}

QUAY = {
    "status": "scanned",
    "data": {
        "Layer": {
            "Features": [
                {
                    "Name": "@fastify/static",
                    "Version": "7.0.0",
                    "Vulnerabilities": [
                        {
                            "Name": "CVE-2026-18427",
                            "Severity": "High",
                            "FixedBy": "7.0.1",
                        }
                    ],
                }
            ]
        }
    },
}


class TestClairReport(unittest.TestCase):
    def test_normalized_severity_when_keyed_by_internal_id(self):
        report = {
            "packages": {"1": {"name": "axios", "version": "1.6.0", "kind": "npm"}},
            "vulnerabilities": {
                "hash-1": {
                    "id": "hash-1",
                    "name": "CVE-2026-42044",
                    "severity": "",
                    "normalized_severity": "High",
                    "fixed_in_version": "1.7.0",
                }
            },
            "package_vulnerabilities": {"1": ["hash-1"]},
        }
        rows = clair_report.rows_from_clair_v4(report)
        self.assertEqual(rows[0]["cve"], "CVE-2026-42044")
        self.assertEqual(rows[0]["severity"], "high")
        self.assertEqual(rows[0]["fixed_in"], "1.7.0")

    def test_clair_v4_rows_include_fix_version(self):
        rows = clair_report.rows_from_clair_v4(CLAIR_V4)
        by_pkg = {row["package"]: row for row in rows}
        self.assertEqual(by_pkg["axios@1.6.0"]["fixed_in"], "1.7.0")
        self.assertEqual(by_pkg["axios@1.6.0"]["severity"], "high")
        self.assertEqual(by_pkg["rsync@3.2.7-1.el9"]["cve"], "CVE-2026-10001")

    def test_quay_features(self):
        rows = clair_report.rows_from_quay_report(QUAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["package"], "@fastify/static@7.0.0")
        self.assertEqual(rows[0]["fixed_in"], "7.0.1")

    def test_extract_from_noisy_log(self):
        log = "Running clair-action...\n" + json.dumps(CLAIR_V4) + "\nDone\n"
        rows = clair_report.rows_from_scan_text(log)
        packages = {row["package"] for row in rows}
        self.assertIn("axios@1.6.0", packages)
        self.assertIn("rsync@3.2.7-1.el9", packages)

    def test_empty_log(self):
        self.assertEqual(clair_report.rows_from_scan_text("no report here"), [])

    def test_family_strips_version(self):
        self.assertEqual(analyze_cve_report.package_family("axios@1.6.0"), "axios")
        self.assertTrue(
            analyze_cve_report.package_family("@fastify/static@7.0.0").startswith("@fastify")
        )
        self.assertEqual(
            analyze_cve_report.classify_layer("axios@1.6.0"),
            "application",
        )
        self.assertEqual(
            analyze_cve_report.classify_layer("rsync@3.2.7-1.el9"),
            "os_rpm",
        )


if __name__ == "__main__":
    unittest.main()
