import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'toolbox/helpers'))
from antimicrox_switcher import SwitcherScope, update_scope
from antimicrox_live import LiveSession


class SwitcherScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.config = self.home/'rc.xml'
        self.original = (b'<?xml version="1.0"?>\r\n<labwc_config>\r\n'
            b'<!-- user comment -->\r\n<windowRules>\r\n'
            b'<windowRule identifier="emulationstation" skipWindowSwitcher="no" />\r\n'
            b'</windowRules>\r\n</labwc_config>\r\n')
        self.config.write_bytes(self.original)
        self.config.chmod(0o640)
        self.reload = Mock()
        self.scope = SwitcherScope(self.home, self.config, self.reload)
        env = patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'})
        env.start(); self.addCleanup(env.stop)

    def test_only_adds_es_exclusion_and_restores_exact_original_bytes_and_mode(self):
        self.assertTrue(self.scope.hide('first'))
        rules = ET.fromstring(self.config.read_bytes()).findall('./windowRules/windowRule')
        self.assertEqual(rules[-1].attrib,
                         {'identifier': 'emulationstation', 'skipWindowSwitcher': 'yes'})
        self.assertIn(b'<!-- user comment -->', self.config.read_bytes())
        self.assertEqual(stat.S_IMODE(self.scope.state.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assertTrue(self.scope.restore('first'))
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse(self.scope.state.exists())
        self.assertEqual(self.reload.call_count, 2)

    def test_keeps_unrelated_edits_made_during_the_session(self):
        self.scope.hide('first')
        updated = self.config.read_bytes().replace(b'<!-- user comment -->', b'<!-- edited -->')
        self.config.write_bytes(updated)
        self.scope.restore('first')
        self.assertEqual(self.config.read_bytes(), self.original.replace(b'user comment', b'edited'))

    def test_repeated_start_and_wrong_session_cleanup_are_harmless(self):
        self.scope.hide('first')
        injected = self.config.read_bytes()
        self.scope.hide('first')
        self.assertEqual(self.reload.call_count, 1)
        self.assertFalse(self.scope.restore('old'))
        self.assertEqual(self.config.read_bytes(), injected)
        self.scope.restore('first')
        self.assertFalse(self.scope.restore('first'))

    def test_new_session_recovers_previous_owned_rule(self):
        self.scope.hide('first')
        self.scope.hide('second')
        self.assertNotIn(b'switcher first', self.config.read_bytes())
        self.assertIn(b'switcher second', self.config.read_bytes())
        self.scope.restore('second')
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_missing_and_self_closing_sections_restore_without_reformatting(self):
        for raw in [b'<labwc_config><!--keep--></labwc_config>',
                    b'<labwc_config><windowRules /></labwc_config>']:
            self.config.write_bytes(raw)
            self.scope.hide('first')
            self.scope.restore('first')
            self.assertEqual(self.config.read_bytes(), raw)

    def test_added_rules_survive_cleanup_of_previously_empty_section(self):
        self.config.write_bytes(b'<labwc_config><windowRules /></labwc_config>')
        self.scope.hide('first')
        self.config.write_bytes(self.config.read_bytes().replace(
            b'</windowRules>', b'<windowRule identifier="other" /></windowRules>'))
        self.scope.restore('first')
        self.assertEqual(ET.fromstring(self.config.read_bytes()).find('./windowRules/windowRule').get('identifier'), 'other')

    def test_reconfigure_failure_rolls_back_config_and_keeps_recovery_for_retry(self):
        self.reload.side_effect = subprocess.CalledProcessError(1, ['labwc', '--reconfigure'])
        with self.assertRaises(subprocess.CalledProcessError):
            self.scope.hide('first')
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertTrue(self.scope.state.exists())
        self.reload.side_effect = None
        self.scope.restore('first')
        self.assertFalse(self.scope.state.exists())

    def test_modified_owned_rule_is_not_overwritten(self):
        self.scope.hide('first')
        self.config.write_bytes(self.config.read_bytes().replace(b'skipWindowSwitcher="yes"', b'skipWindowSwitcher="no"'))
        modified = self.config.read_bytes()
        with self.assertRaises(ValueError):
            self.scope.restore('first')
        self.assertEqual(self.config.read_bytes(), modified)
        self.assertTrue(self.scope.state.exists())

    def test_xorg_or_missing_config_leaves_everything_untouched(self):
        with patch.dict(os.environ, {'WAYLAND_DISPLAY': ''}):
            self.assertFalse(self.scope.hide('first'))
        self.config.unlink()
        self.assertFalse(self.scope.hide('first'))
        self.assertFalse(self.scope.state.exists())
        self.reload.assert_not_called()

    def test_symlinked_config_keeps_symlink_and_restores_target(self):
        link = self.home/'linked.xml'
        link.symlink_to(self.config)
        scope = SwitcherScope(self.home, link, self.reload)
        scope.hide('first'); scope.restore('first')
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_live_lifecycle_only_hides_while_running_and_restores_on_recovery(self):
        romroot = self.home/'roms'; rom = romroot/'Game.wine'; rom.mkdir(parents=True)
        profile = self.home/'profile.amgp'
        profile.write_text('<gamecontroller><sets/></gamecontroller>')
        session = LiveSession(self.home, romroot)
        with patch('antimicrox_switcher.SwitcherScope', return_value=self.scope):
            data = session.prepare(rom, profile)
            self.assertFalse(self.scope.state.exists())
            session.mark(str(rom)+'other', phase='running')
            self.assertFalse(self.scope.state.exists())
            session.mark(str(rom), phase='running')
            self.assertEqual(json.loads(self.scope.state.read_text())['session_id'], data['session_id'])
            self.assertNotEqual(self.config.read_bytes(), self.original)
            session.finish('recovered', str(rom))
            self.assertEqual(self.config.read_bytes(), self.original)
            session.finish('again'); session.clear()
            self.assertFalse(self.scope.state.exists())

    def test_failed_optional_scope_never_stops_the_workflow(self):
        with patch('antimicrox_switcher.SwitcherScope', side_effect=OSError('unavailable')):
            self.assertFalse(update_scope(self.home, 'hide', 'first'))
