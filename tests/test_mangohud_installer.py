import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mangohud_installer", ROOT / "scripts/install-mangohud-controls-test.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class MangoHudInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "ultimate-wine-toolbox"
        self.hook = Path(self.temp.name) / "scripts/ultimate-wine-toolbox-mangohud.sh"
        self.home.mkdir()
        (self.home / "VERSION").write_text("0.8.1\n")
        self.original = {
            "toolbox/modules/graphics.sh": b"#!/bin/bash\nold=1\n",
            installer.HOOK: b"#!/bin/bash\necho old\n",
            "toolbox/helpers/mangohud_settings.py": None,
            "toolbox/lang/fr.sh": b"#!/bin/bash\nlabel=ancien\n",
            "toolbox/docs/fr/mangohud.txt": b"Old documentation\n",
        }
        self.payload = {
            "files": {name: content.decode().replace("old", "new") if content else "# new helper\n"
                      for name, content in self.original.items()},
            "base_hashes": {name: installer.digest(content) if content else None
                            for name, content in self.original.items()},
        }
        for name, content in self.original.items():
            if content is not None:
                path = self.home / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(0o640)
        self.hook.parent.mkdir()
        self.hook.write_bytes(self.original[installer.HOOK])
        self.hook.chmod(0o750)
        self.settings = self.home / installer.SETTINGS
        self.settings.parent.mkdir()
        self.settings.write_text('{"global": {"display": "minimal"}}\n')
        self.original_settings = self.settings.read_bytes()

    def assert_original(self):
        for name, content in self.original.items():
            path = self.home / name
            if content is None:
                self.assertFalse(path.exists())
            else:
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.hook.read_bytes(), self.original[installer.HOOK])
        self.assertEqual(self.hook.stat().st_mode & 0o777, 0o750)
        self.assertEqual(self.settings.read_bytes(), self.original_settings)
        self.assertFalse((self.home / installer.STATE).exists())

    def test_embedded_snapshot_is_complete_and_valid(self):
        payload = installer.unpack()
        for name, content in payload["files"].items():
            self.assertTrue(content, name)
            self.assertIn(name, payload['base_hashes'])
            if name.endswith('.py'):
                compile(content, name, 'exec')
        # The installer remains a fixed snapshot when later topic branches
        # extend shared translations or documentation.
        helper = 'toolbox/helpers/mangohud_settings.py'
        self.assertEqual((ROOT / helper).read_text(), payload['files'][helper])

    def test_install_repeat_restore_preserves_settings_and_other_files(self):
        unrelated = self.home / "config/runners.json"
        unrelated.write_text('{"keep": true}\n')
        with patch.object(installer, "unpack", return_value=self.payload):
            installer.install(self.home, self.hook)
            for path, name in installer.targets(self.home, self.hook, self.payload):
                self.assertEqual(path.read_text(), self.payload["files"][name])
                if name.endswith(".sh"):
                    self.assertTrue(path.stat().st_mode & 0o111)
            self.assertEqual(self.settings.read_bytes(), self.original_settings)
            installer.install(self.home, self.hook)
            self.settings.write_text('{"global": {"fps": "144"}}\n')
            installer.restore(self.home)
            self.assert_original()
            installer.restore(self.home)
        self.assertEqual(unrelated.read_text(), '{"keep": true}\n')

    def test_unrecognized_base_changes_nothing(self):
        path = self.home / "toolbox/modules/graphics.sh"
        path.write_text("# another test\n")
        with patch.object(installer, "unpack", return_value=self.payload), self.assertRaisesRegex(ValueError, "Version différente"):
            installer.install(self.home, self.hook)
        self.assertEqual(path.read_text(), "# another test\n")
        self.assertEqual(self.hook.read_bytes(), self.original[installer.HOOK])
        self.assertFalse((self.home / installer.STATE).exists())

    def test_write_failure_rolls_back(self):
        original_write = installer.write_atomic
        failed = False
        def fail_once(path, data, mode=0o644):
            nonlocal failed
            if path == self.hook and not failed:
                failed = True
                raise OSError("simulated disk failure")
            original_write(path, data, mode)
        with patch.object(installer, "unpack", return_value=self.payload), patch.object(installer, "write_atomic", side_effect=fail_once):
            with self.assertRaises(OSError):
                installer.install(self.home, self.hook)
        self.assert_original()

    def test_restore_refuses_to_overwrite_later_changes(self):
        with patch.object(installer, "unpack", return_value=self.payload):
            installer.install(self.home, self.hook)
        self.hook.write_text("# later hook\n")
        with self.assertRaisesRegex(ValueError, "a changé"):
            installer.restore(self.home)
        self.assertEqual(self.hook.read_text(), "# later hook\n")
        self.assertTrue((self.home / installer.STATE).exists())


if __name__ == "__main__":
    unittest.main()
