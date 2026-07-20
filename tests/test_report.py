from __future__ import annotations

import unittest

from spacekeeper.models import ScanResult
from spacekeeper.report import render_html_report, render_text


class ReportTests(unittest.TestCase):
    def test_render_html_report_contains_doctype_and_title(self) -> None:
        res = ScanResult(
            roots=["/Users/test"],
            started_at=100.0,
            finished_at=102.0,
            scanned_files=50,
            scanned_bytes=1000000,
            scanned_logical_bytes=1000000,
            review_candidate_bytes=500000,
            candidate_bytes_by_risk={"low": 300000, "medium": 200000, "high": 0},
            volume_total_bytes=100000000,
            volume_used_bytes=50000000,
            volume_free_bytes=50000000,
            skipped_symlinks=0,
            skipped_cloud_dirs=0,
            skipped_excluded_paths=0,
            permission_denied=0,
            file_candidate_count=0,
            cache_candidate_count=0,
            duplicate_group_count=0,
            duplicate_reclaimable_bytes=0,
        )
        html = render_html_report(res)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Spacekeeper Audit Report", html)
        self.assertIn("SPACEKEEPER READ-ONLY REPORT", html)


if __name__ == "__main__":
    unittest.main()
