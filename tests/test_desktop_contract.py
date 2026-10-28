from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
TAURI_DIR = DESKTOP / "src-tauri"
TAURI_CONFIG = json.loads((TAURI_DIR / "tauri.conf.json").read_text())
MAIN_RS = (TAURI_DIR / "src" / "main.rs").read_text()
BUILD_SIDECAR = (DESKTOP / "build-sidecar.sh").read_text()
FINALIZE_RELEASE = (DESKTOP / "finalize-macos-release.sh").read_text()
BUILD_MACOS = (DESKTOP / "build-macos.sh").read_text()
PACKAGE_JSON = json.loads((DESKTOP / "package.json").read_text())


class DesktopBundleContractTests(unittest.TestCase):
    def test_tauri_build_always_prepares_bundled_runtime(self) -> None:
        self.assertEqual(
            TAURI_CONFIG["build"]["beforeBuildCommand"],
            "./build-sidecar.sh",
        )
        self.assertEqual(
            TAURI_CONFIG["build"]["beforeDevCommand"],
            "./build-sidecar.sh",
        )
        self.assertEqual(
            TAURI_CONFIG["bundle"]["resources"],
            {"../.sidecar-dist/spacekeeper-server/": "sidecar/"},
        )
        self.assertEqual(
            TAURI_CONFIG["bundle"]["macOS"]["signingIdentity"],
            "-",
        )

    def test_version_is_the_same_everywhere(self) -> None:
        """버전이 네 곳(파이썬·Tauri·Cargo·npm)에 흩어져 있어 쉽게 어긋난다.

        릴리스 파일명과 앱 정보가 서로 다른 버전을 말하면 사용자가 무엇을 받았는지
        알 수 없으므로 여기서 묶어 둔다.
        """
        import re

        from spacekeeper import __version__ as py_version

        cargo = (TAURI_DIR / "Cargo.toml").read_text(encoding="utf-8")
        cargo_version = re.search(r'^version\s*=\s*"([^"]+)"', cargo, re.M).group(1)
        self.assertEqual(TAURI_CONFIG["version"], py_version)
        self.assertEqual(PACKAGE_JSON["version"], py_version)
        self.assertEqual(cargo_version, py_version)

    def test_declared_support_matches_what_we_actually_ship(self) -> None:
        """선언한 최소 macOS 버전이 실제 빌드(Apple Silicon 전용)와 맞아야 한다.

        Tauri 기본값은 10.13인데, 우리는 arm64 바이너리만 낸다. 기본값을 그대로
        두면 Info.plist가 Intel Mac도 지원한다고 거짓말하게 된다 — '정직한 숫자'를
        내건 앱이 지원 범위를 속이는 셈이라 여기서 막는다.
        """
        minimum = TAURI_CONFIG["bundle"]["macOS"].get("minimumSystemVersion")
        self.assertIsNotNone(minimum, "최소 macOS 버전을 명시해야 합니다")
        self.assertGreaterEqual(
            int(str(minimum).split(".")[0]),
            11,
            "Apple Silicon은 macOS 11부터입니다",
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            f"macOS {str(minimum).split('.')[0]}",
            readme,
            "README가 알리는 요구사항과 번들 설정이 어긋납니다",
        )
        self.assertIn("Apple Silicon", readme)

    def test_sidecar_is_self_contained_and_includes_web_assets(self) -> None:
        self.assertIn("--onedir", BUILD_SIDECAR)
        self.assertIn("spacekeeper/web:spacekeeper/web", BUILD_SIDECAR)
        self.assertIn("com.apple.FinderInfo", BUILD_SIDECAR)
        self.assertIn("pyinstaller==6.21.0", (DESKTOP / "sidecar-requirements.txt").read_text())

    def test_release_build_seals_complete_app_and_verifies_dmg(self) -> None:
        # 기본 build는 자가 치유 래퍼를 거치고, 기존 체인은 build:tauri로 보존한다.
        self.assertEqual(PACKAGE_JSON["scripts"]["build"], "./build-macos.sh")
        self.assertEqual(
            PACKAGE_JSON["scripts"]["build:tauri"],
            "tauri build && ./finalize-macos-release.sh",
        )
        # 래퍼는 번들 완성 후 메타데이터를 제거하고 ad-hoc 재서명한 뒤 finalize로 넘긴다.
        self.assertIn("npx tauri build", BUILD_MACOS)
        self.assertIn("xattr -cr", BUILD_MACOS)
        self.assertIn("codesign --force --deep --sign -", BUILD_MACOS)
        self.assertIn("codesign --verify --deep --strict", BUILD_MACOS)
        self.assertIn("./finalize-macos-release.sh", BUILD_MACOS)
        self.assertIn("codesign --verify --deep --strict", FINALIZE_RELEASE)
        self.assertIn("hdiutil verify", FINALIZE_RELEASE)
        self.assertIn("--filesystem APFS", FINALIZE_RELEASE)
        self.assertIn("spacekeeper-release-stage", FINALIZE_RELEASE)
        self.assertIn("CFBundleShortVersionString", FINALIZE_RELEASE)
        self.assertIn('arm64) RELEASE_ARCH="aarch64"', FINALIZE_RELEASE)
        self.assertIn("com.apple.FinderInfo", FINALIZE_RELEASE)

    def test_native_app_never_falls_back_to_system_python(self) -> None:
        self.assertIn("std::env::current_exe()", MAIN_RS)
        self.assertIn('.join("Resources")', MAIN_RS)
        self.assertIn('.join("sidecar")', MAIN_RS)
        self.assertIn('Command::new(sidecar)', MAIN_RS)
        self.assertNotIn('Command::new("python3")', MAIN_RS)
        self.assertFalse((DESKTOP / "stage-runtime.sh").exists())

    def test_native_app_uses_dynamic_port_and_per_launch_api_token(self) -> None:
        self.assertIn('File::open("/dev/urandom")', MAIN_RS)
        self.assertIn(
            "TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], 0)))",
            MAIN_RS,
        )
        self.assertIn('"SPACEKEEPER_API_TOKEN"', MAIN_RS)
        self.assertIn('"SPACEKEEPER_PORT"', MAIN_RS)
        self.assertIn("server_is_ready(port, &api_token)", MAIN_RS)
        self.assertNotIn("const PORT: u16 = 8765", MAIN_RS)
        self.assertIsNotNone(TAURI_CONFIG["app"]["security"]["csp"])


    def test_hidden_title_bar_always_comes_with_a_way_to_move_the_window(self) -> None:
        """제목줄을 걷어냈으면 창을 끌 수 있는 띠와 그 권한이 반드시 함께 있어야 한다.

        셋 중 하나만 빠져도 사용자는 창을 옮길 수 없다. 회색 제목줄이 있는 것보다 나쁘다.
        """
        window = TAURI_CONFIG["app"]["windows"][0]
        if window.get("titleBarStyle") != "Overlay":
            return
        index_html = (ROOT / "spacekeeper" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("data-tauri-drag-region", index_html)
        style = (ROOT / "spacekeeper" / "web" / "style.css").read_text(encoding="utf-8")
        self.assertIn('html[data-shell="desktop"] .titlebar-drag', style)

        remote = json.loads((TAURI_DIR / "capabilities" / "dashboard-drag.json").read_text())
        self.assertIn("core:window:allow-start-dragging", remote["permissions"])

    def test_dashboard_gets_only_window_drag_permissions(self) -> None:
        """대시보드는 원격(127.0.0.1) 페이지다. 거기에 열어주는 네이티브 권한은
        창 끌기와 더블클릭 확대뿐이어야 한다 — 슬쩍 넓어지면 여기서 막는다."""
        remote = json.loads((TAURI_DIR / "capabilities" / "dashboard-drag.json").read_text())
        self.assertEqual(remote["windows"], ["main"])
        self.assertEqual(remote["remote"]["urls"], ["http://127.0.0.1:*"])
        self.assertEqual(
            sorted(remote["permissions"]),
            ["core:window:allow-internal-toggle-maximize", "core:window:allow-start-dragging"],
        )

    def test_app_menu_has_a_working_edit_menu(self) -> None:
        """맥에서는 편집 메뉴가 있어야 입력칸에서 ⌘C·⌘V·⌘A가 동작한다."""
        self.assertIn(".menu(build_app_menu)", MAIN_RS)
        for item in ("PredefinedMenuItem::copy", "PredefinedMenuItem::paste", "PredefinedMenuItem::select_all"):
            self.assertIn(item, MAIN_RS)
        self.assertIn("PredefinedMenuItem::about", MAIN_RS)

if __name__ == "__main__":
    unittest.main()
