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


class I18nNoRewriteLoopTests(unittest.TestCase):
    """영어 모드에서 번역이 원문과 같으면 아무것도 쓰지 않아야 한다.

    쓰면 MutationObserver가 다시 불려 페이지가 멈춘다(2026-11-20, 시스템 데이터의
    "Command Line Tools").
    """

    def test_identical_translation_does_not_rewrite_text(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            self.skipTest("node가 없어 i18n.js를 실행할 수 없습니다.")
        script = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const make = new Function("window","localStorage","navigator","document","Node","NodeFilter","MutationObserver",
  src + "; return { EN, translateText, translateNode };");
const api = make({}, { getItem: () => "en" }, { language: "en" },
  { addEventListener() {} }, { TEXT_NODE: 3, ELEMENT_NODE: 1 }, {}, function () {});
const same = Object.entries(api.EN).filter(([k, v]) => k === v).map(([k]) => k);
let writes = 0;
for (const key of same.concat(["Command Line Tools"])) {
  let value = key;
  const text = { nodeType: 3, get nodeValue() { return value; }, set nodeValue(v) { writes++; value = v; } };
  api.translateText(text);
}
const translated = { nodeType: 3, nodeValue: "취소" };
api.translateText(translated);
console.log(JSON.stringify({ writes, translated: translated.nodeValue }));
"""
        out = subprocess.run(
            [node, "-e", script, str(ROOT / "spacekeeper" / "web" / "i18n.js")],
            capture_output=True, text=True, timeout=30, check=True,
        )
        result = __import__("json").loads(out.stdout)
        self.assertEqual(result["writes"], 0)
        self.assertEqual(result["translated"], "Cancel")

    def test_attribute_and_text_writes_go_through_change_checks(self) -> None:
        i18n = (ROOT / "spacekeeper" / "web" / "i18n.js").read_text(encoding="utf-8")
        self.assertNotIn("textNode.nodeValue = ", i18n.replace(
            "if (value !== textNode.nodeValue) textNode.nodeValue = value;", ""))
        self.assertNotIn("el.setAttribute(attr, EN[key])", i18n)
        self.assertNotIn("el.setAttribute(attr, patterned)", i18n)
