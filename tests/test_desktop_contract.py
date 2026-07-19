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

    def test_sidecar_is_self_contained_and_includes_web_assets(self) -> None:
        self.assertIn("--onedir", BUILD_SIDECAR)
        self.assertIn("spacekeeper/web:spacekeeper/web", BUILD_SIDECAR)
        self.assertIn("com.apple.FinderInfo", BUILD_SIDECAR)
        self.assertIn("pyinstaller==6.21.0", (DESKTOP / "sidecar-requirements.txt").read_text())

    def test_release_build_seals_complete_app_and_verifies_dmg(self) -> None:
        self.assertEqual(
            PACKAGE_JSON["scripts"]["build"],
            "tauri build && ./finalize-macos-release.sh",
        )
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


if __name__ == "__main__":
    unittest.main()
