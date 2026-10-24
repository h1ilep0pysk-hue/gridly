"""Тесты дефолтов MacTweaks, поля mydock_enabled и миграции tweaks.json."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _qt_env  # noqa: F401
from core import tweaks as tw


class TweaksDefaultsTests(unittest.TestCase):
    def test_mydock_and_shell_on_by_default(self):
        t = tw.MacTweaks()
        self.assertTrue(t.mydock_enabled)
        self.assertTrue(t.shell_enabled)
        self.assertEqual(t.schema_version, tw.SCHEMA_VERSION)

    def test_mydock_flag_round_trips(self):
        t = tw.MacTweaks.from_dict({"mydock_enabled": True})
        self.assertTrue(t.mydock_enabled)
        self.assertTrue(tw.MacTweaks.from_dict(t.to_dict()).mydock_enabled)


class TweaksMigrationTests(unittest.TestCase):
    def _load(self, payload):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "tweaks.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch.object(tw, "tweaks_path", return_value=path):
            result = tw.load_tweaks()
        return result, json.loads(path.read_text(encoding="utf-8"))

    def test_legacy_file_gets_shell_on_and_is_rewritten(self):
        result, saved = self._load({"enabled": True, "shell_enabled": False})
        self.assertTrue(result.shell_enabled)
        self.assertEqual(saved["schema_version"], tw.SCHEMA_VERSION)
        self.assertTrue(saved["shell_enabled"])

    def test_v2_file_switches_dock_to_mydock_once(self):
        result, saved = self._load({"schema_version": 2,
                                    "shell_enabled": True,
                                    "mydock_enabled": False})
        self.assertTrue(result.mydock_enabled)
        self.assertTrue(saved["mydock_enabled"])
        self.assertEqual(saved["schema_version"], tw.SCHEMA_VERSION)

    def test_current_file_keeps_explicit_choice(self):
        result, saved = self._load({"schema_version": tw.SCHEMA_VERSION,
                                    "enabled": True,
                                    "shell_enabled": False})
        self.assertFalse(result.shell_enabled)
        self.assertFalse(saved["shell_enabled"])

    def test_migration_is_one_shot(self):
        raw = {"shell_enabled": False}
        self.assertTrue(tw._migrate(raw))
        raw["shell_enabled"] = False  # пользователь выключил уже после миграции
        self.assertFalse(tw._migrate(raw))
        self.assertFalse(raw["shell_enabled"])


if __name__ == "__main__":
    unittest.main()
