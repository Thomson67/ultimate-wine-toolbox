import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "toolbox/helpers"
spec = importlib.util.spec_from_file_location("mangohud_settings", HELPERS / "mangohud_settings.py")
mh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mh)


class MangoHudControlsTests(unittest.TestCase):
    def test_custom_fps_above_60_and_zero_override_without_touching_other_limiters(self):
        with tempfile.TemporaryDirectory() as folder:
            game = "/windows/High refresh.wine"
            mh.save_setting(folder, "", "fps", "240")
            mh.save_setting(folder, game, "fps", "141")
            mh.save_setting(folder, game, "method", "late")
            payload = 'DXVK_FRAME_RATE=60 MANGOHUD_CONFIG="position=top-right,fps_limit=90"'
            applied = mh.apply_config(payload, mh.settings(folder, game))
            self.assertIn("fps_limit=141", applied)
            self.assertIn("fps_limit_method=late", applied)
            self.assertIn("DXVK_FRAME_RATE=60", applied)
            self.assertNotIn("fps_limit=90", applied)
            mh.save_setting(folder, game, "fps", "0")
            self.assertIn("fps_limit=0", mh.config_options(mh.settings(folder, game)))
            mh.save_setting(folder, game, "fps", "inherit")
            self.assertIn("fps_limit=240", mh.config_options(mh.settings(folder, game)))

    def test_per_game_inheritance_and_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            game = "/userdata/roms/windows/A game [test].wine"
            mh.save_setting(folder, "", "opengl", "on")
            mh.save_setting(folder, "", "vulkan", "mailbox")
            mh.save_setting(folder, game, "opengl", "off")
            self.assertEqual(mh.settings(folder, game)["opengl"], "off")
            self.assertEqual(mh.settings(folder, game)["vulkan"], "mailbox")
            self.assertEqual(mh.settings(folder, "/other")["opengl"], "on")
            mh.save_setting(folder, game, "opengl", "inherit")
            self.assertEqual(mh.settings(folder, game)["opengl"], "on")
            self.assertNotIn(game, mh.load(folder)["games"])

    def test_invalid_values_and_corrupt_file_do_not_overwrite_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            mh.save_setting(folder, "", "opengl", "on")
            path = Path(folder) / "mangohud-settings.json"
            original = path.read_bytes()
            for key, value in (("fps", "-1"), ("fps", "60,30"), ("fps", "1001"),
                               ("fps", "６０"), ("fps", "60;echo bad"), ("vulkan", "invalid")):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    mh.save_setting(folder, "", key, value)
                self.assertEqual(path.read_bytes(), original)
            path.write_text("{broken")
            with self.assertRaises(ValueError):
                mh.save_setting(folder, "", "vulkan", "mailbox")
            self.assertEqual(path.read_text(), "{broken")

    def test_existing_display_profile_migrates_without_forcing_performance(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(mh.config_options(mh.settings(folder)), [])
            (Path(folder) / "mangohud-profile").write_text("minimal\n")
            self.assertEqual(mh.settings(folder)["display"], "minimal")
            mh.save_setting(folder, "", "display", "hidden")
            self.assertEqual(mh.config_options(mh.settings(folder)), ["no_display"])

    def test_custom_config_is_merged_and_restored_with_quoting(self):
        payload = 'FOO="two  words" MANGOHUD_CONFIG=\'position=top-left,custom_text=My game,vsync=3,no_display\' BAR=1'
        applied = mh.apply_config(payload, {"vulkan": "mailbox", "display": "detailed", "opengl": "on"})
        config = next(v.split("=", 1)[1] for v in shlex.split(applied) if v.startswith("MANGOHUD_CONFIG="))
        self.assertIn("custom_text=My game", config)
        self.assertIn("vulkan_present_mode=mailbox", config)
        self.assertNotIn("vsync=3", config)
        self.assertNotIn("no_display", config)
        restored = mh.restore_config(applied)
        self.assertIn('FOO="two  words"', restored)
        self.assertEqual(sorted(shlex.split(restored)), sorted(shlex.split(payload)))
        self.assertNotIn(mh.BACKUP, restored)

    def test_default_display_reads_existing_config_file(self):
        applied = mh.apply_config("FOO=1", {"display": "default", "vulkan": "mailbox"})
        self.assertIn("MANGOHUD_CONFIG=read_cfg,vulkan_present_mode=mailbox", applied)

    def run_hook_rewrite(self, path, enabled, config, game):
        hook = (ROOT / "toolbox/hooks/mangohud-game-event.sh").read_text()
        code = hook.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        subprocess.run(["python3", "-", str(path), str(int(enabled)), "0",
                        "libMangoHud_shim.so", "/runtime/lib64:/runtime/lib32",
                        "/runtime", "default", str(HELPERS), str(config), game],
                       input=code, text=True, check=True, capture_output=True)

    def test_hook_repeat_change_disable_restores_user_config_and_other_env(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            path = directory / "autorun.cmd"
            game = "/windows/Azahar.wine"
            original = 'DIR=game\nENV=FOO="two  words" MANGOHUD_CONFIG="position=top-left,vsync=3" UMU_DIRECT_GAME=1\nCMD="azahar.exe"\n'
            path.write_text(original)
            mh.save_setting(directory, game, "vulkan", "mailbox")
            mh.save_setting(directory, game, "display", "hidden")
            self.run_hook_rewrite(path, True, directory, game)
            first = path.read_text()
            self.assertIn("no_display,vulkan_present_mode=mailbox", first)
            self.run_hook_rewrite(path, True, directory, game)
            env = lambda text: sorted(shlex.split(next(v[4:] for v in text.splitlines() if v.startswith("ENV="))))
            self.assertEqual(env(first), env(path.read_text()))
            mh.save_setting(directory, game, "vulkan", "on")
            self.run_hook_rewrite(path, True, directory, game)
            self.assertNotIn("vulkan_present_mode=mailbox", path.read_text())
            self.assertIn("vulkan_present_mode=fifo", path.read_text())
            self.run_hook_rewrite(path, False, directory, game)
            stopped = path.read_text()
            self.assertEqual(env(stopped), env(original))
            self.assertIn('FOO="two  words"', stopped)
            self.assertIn('CMD="azahar.exe"', stopped)
            self.assertNotIn("UWT_MANGOHUD", stopped)

    def test_hook_without_env_cleans_every_generated_setting(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            path = directory / "autorun.cmd"
            original = 'DIR=game\nCMD=game.exe\n'
            path.write_text(original)
            mh.save_setting(directory, "", "vulkan", "mailbox")
            self.run_hook_rewrite(path, True, directory, "/game.wine")
            self.assertIn("vulkan_present_mode=mailbox", path.read_text())
            self.run_hook_rewrite(path, False, directory, "/game.wine")
            self.assertEqual(path.read_text(), original)

    def test_menu_writes_per_game_setting_without_changing_global(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            game = "/windows/Azahar [Vulkan].wine"
            mh.save_setting(directory / "config", "", "vulkan", "on")
            code = '''source "$WT_ROOT/lib/common.sh"
WT_LANGUAGE=fr; load_i18n
WT_HOME="$TEST_HOME"
source "$WT_ROOT/modules/graphics.sh"
menu_select() { printf mailbox; }
mangohud_control_edit vulkan "$TEST_GAME"
'''
            result = subprocess.run(["bash", "-c", code], env=dict(os.environ,
                WT_ROOT=str(ROOT / "toolbox"), TEST_HOME=folder, TEST_GAME=game),
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(mh.settings(directory / "config", game)["vulkan"], "mailbox")
            self.assertEqual(mh.settings(directory / "config")["vulkan"], "on")


if __name__ == "__main__":
    unittest.main()
