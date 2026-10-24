"""Конфиг и экспорт macOS-оверлея (чистый Python, без PyObjC)."""
import json
import tempfile
import unittest
from pathlib import Path

import _qt_env  # noqa: F401  (путь к проекту)
from core import mac_overlay
from core.tweaks import MacTweaks


class OverlayConfigTests(unittest.TestCase):
    def test_parse_bundles_strips_and_dedupes(self):
        self.assertEqual(
            mac_overlay.parse_bundles(" a.b , c.d,, a.b ,"),
            ["a.b", "c.d"])
        self.assertEqual(mac_overlay.parse_bundles(""), [])

    def test_config_contains_titlebar_settings(self):
        t = MacTweaks(titlebar_wrap_enabled=True,
                      titlebar_wrap_bundles="com.apple.TextEdit, com.x.y")
        cfg = mac_overlay.overlay_config(t)
        self.assertTrue(cfg["titlebar_enabled"])
        self.assertEqual(cfg["titlebar_bundles"],
                         ["com.apple.TextEdit", "com.x.y"])
        self.assertIn("enabled", cfg)
        self.assertIn("level", cfg)

    def test_titlebar_off_by_default(self):
        cfg = mac_overlay.overlay_config(MacTweaks())
        self.assertFalse(cfg["titlebar_enabled"])

    def test_export_copies_titlebar_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = mac_overlay.export_overlay(MacTweaks(), Path(tmp))
            names = {p.name for p in copied}
            self.assertIn("macos_titlebar_wrap.py", names)
            self.assertIn("macos_global_overlay.py", names)
            config = json.loads(
                (Path(tmp) / "macos_overlay.json").read_text(encoding="utf-8"))
            self.assertIn("titlebar_bundles", config)


if __name__ == "__main__":
    unittest.main()
