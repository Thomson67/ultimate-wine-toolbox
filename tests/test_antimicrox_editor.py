import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('amx_editor', ROOT/'toolbox/helpers/antimicrox_editor.py')
editor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(editor)


class EditorGeometryTests(unittest.TestCase):
    def test_primary_monitor_is_used_instead_of_combined_desktop(self):
        text = ('Screen 0: current 3840 x 1080, maximum 32767 x 32767\n'
                'DP-1 connected 1920x1080+0+0\n'
                'HDMI-1 connected primary 1920x1080+1920+0\n')
        self.assertEqual(editor.display_bounds(text), (1920, 1080, 1920, 0))

    def test_small_window_is_enlarged_without_changing_profile_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'antimicrox/antimicrox_settings.ini'
            path.parent.mkdir()
            path.write_text('[General]\nWindowSize=@Size(650 580)\nLanguage=fr\n'
                            '[Controllers]\nProfile=/userdata/My Game.amgp\nWindowSize=keep\n')
            self.assertEqual(editor.prepare(folder, (1920, 1080, 0, 0)), (1600, 900))
            text = path.read_text()
            self.assertIn('WindowPosition=@Point(160 90)', text)
            self.assertIn('Language=fr\n', text)
            self.assertIn('[Controllers]\nProfile=/userdata/My Game.amgp\nWindowSize=keep\n', text)

    def test_small_screen_clamps_geometry_and_repeat_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(editor.prepare(folder, (1280, 800, 0, 0)), (1216, 736))
            path = Path(folder)/'antimicrox/antimicrox_settings.ini'
            before = path.read_text()
            editor.prepare(folder, (1280, 800, 0, 0))
            self.assertEqual(path.read_text(), before)

    def test_larger_user_window_is_preserved_when_it_fits(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'antimicrox/antimicrox_settings.ini'
            path.parent.mkdir()
            path.write_text('[General]\nWindowSize=@Size(2000 1200)\n')
            self.assertEqual(editor.prepare(folder, (3840, 2160, 0, 0)), (2000, 1200))


if __name__ == '__main__':
    unittest.main()
