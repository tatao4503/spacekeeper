import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "spacekeeper" / "web" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "spacekeeper" / "web" / "index.html").read_text(encoding="utf-8")


class WebContractTests(unittest.TestCase):
    def test_html_ids_are_unique_and_cover_javascript_references(self) -> None:
        html_ids = re.findall(r'\bid="([^"]+)"', INDEX_HTML)
        js_ids = set(re.findall(r'getElementById\("([^"]+)"\)', APP_JS))

        self.assertEqual(len(html_ids), len(set(html_ids)))
        self.assertEqual(js_ids - set(html_ids), set())

    def test_low_risk_helper_only_selects_items(self) -> None:
        section = APP_JS.split("function selectLowRisk()", 1)[1].split(
            "function renderFilteredResults()", 1
        )[0]

        self.assertIn("selDash.add", section)
        self.assertNotIn("reclaimIds(", section)
        self.assertNotIn("/api/reclaim", section)

    def test_duplicate_cleanup_is_opt_in_and_preserves_default_copy(self) -> None:
        section = APP_JS.split("function renderDuplicates()", 1)[1].split(
            "function updateDupSelection()", 1
        )[0]

        self.assertIn('class="dup-all"', section)
        self.assertIn('${f.keep ? "disabled" : ""}', section)
        self.assertNotIn('${f.keep ? "" : "checked"}', section)

    def test_interactive_controls_expose_accessible_state(self) -> None:
        self.assertIn('role="group" aria-label="결과 필터 및 작업"', INDEX_HTML)
        self.assertIn('aria-label="격리함 경로 검색"', INDEX_HTML)
        self.assertIn('aria-atomic="true"', INDEX_HTML)
        self.assertIn('aria-expanded="${risk === "low"}"', APP_JS)
        self.assertIn('aria-busy="true"', INDEX_HTML)

    def test_static_buttons_declare_button_type(self) -> None:
        tags = re.findall(r"<button\b[^>]*>", INDEX_HTML)
        missing = [tag for tag in tags if not re.search(r'\btype="button"', tag)]
        self.assertEqual(missing, [])

    def test_diagnostics_explains_bundled_runtime(self) -> None:
        self.assertIn('data.runtime.mode === "bundled"', APP_JS)
        self.assertIn("별도의 Python 설치가 필요하지 않습니다.", APP_JS)

    def test_api_requests_include_app_token(self) -> None:
        self.assertIn('name="spacekeeper-api-token"', INDEX_HTML)
        self.assertIn("__SPACEKEEPER_API_TOKEN__", INDEX_HTML)
        self.assertIn('"X-Spacekeeper-Token"', APP_JS)
        self.assertIn('credentials: "same-origin"', APP_JS)

    def test_auto_quarantine_is_visibly_off_by_default(self) -> None:
        match = re.search(
            r'<input type="checkbox" id="sched-auto-clean"([^>]*)>',
            INDEX_HTML,
        )
        self.assertIsNotNone(match)
        self.assertNotIn("checked", match.group(1))
        self.assertIn("기본은 꺼짐", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
