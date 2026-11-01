"""Keyboard priority must never rewrite a saved game mapping."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'toolbox/helpers'))
import virtual_keyboard as policy
import virtual_keyboard_antimicrox as amx


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.rom = str(self.home/'Game.wine')
        self.source = self.home/'saved.amgp'
        self.source.write_text('<gamecontroller><sets><set index="1"><button index="5"><slots><slot><code>0xff1b</code><mode>keyboard</mode></slot></slots></button><button index="1"><slots><slot><code>0x41</code></slot></slots></button></set></sets></gamecontroller>')
        self.original = self.source.read_bytes()

    def test_only_connected_verified_controllers_select_the_amx_hotkey(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        pad = SimpleNamespace(amx_hotkey='guide',close=Mock())
        with patch('virtual_keyboard_runtime.controllers',return_value=[pad]), \
                patch('antimicrox_hotkey.choices',return_value=[('guide','Pad'),('select','Disconnected')]) as saved:
            self.assertEqual(amx.active_modifiers(),[6])
            saved.assert_not_called()
        pad.close.assert_called_once()

    def test_plain_select_preserved_chord_reserved_and_other_actions_inherited(self):
        root = ET.fromstring(amx.reserved_profile(self.source, [6]))
        self.assertTrue(root.findall('./sets/set[@index="1"]/button[@index="5"]/slots/slot'))
        self.assertFalse(root.findall('./sets/set[@index="2"]/button[@index="5"]/slots/slot'))
        self.assertTrue(root.findall('./sets/set[@index="2"]/button[@index="1"]/slots/slot'))
        self.assertEqual(root.findtext('./sets/set[@index="1"]/button[@index="6"]/setselect'), '2')
        self.assertEqual(root.findtext('./sets/set[@index="2"]/button[@index="6"]/setselect'), '1')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_uses_configured_hotkey_not_sony_button(self):
        root = ET.fromstring(amx.reserved_profile(self.source, [8]))
        self.assertEqual(root.findtext('./sets/set[@index="1"]/button[@index="8"]/setselect'), '2')
        self.assertIsNone(root.find('./sets/set[@index="1"]/button[@index="6"]'))

    def test_existing_held_layer_is_reserved_without_losing_other_chords(self):
        root = ET.fromstring(amx.reserved_profile(self.source, [6]))
        layer = root.find('./sets/set[@index="2"]')
        ET.SubElement(layer.find('button[@index="5"]'), 'slots').append(ET.fromstring('<slot><code>0x42</code></slot>'))
        self.source.write_bytes(ET.tostring(root))
        result = ET.fromstring(amx.reserved_profile(self.source, [6]))
        self.assertEqual(len(result.findall('./sets/set')), 2)
        self.assertTrue(result.findall('./sets/set[@index="1"]/button[@index="5"]/slots/slot'))
        self.assertFalse(result.findall('./sets/set[@index="2"]/button[@index="5"]/slots/slot'))
        self.assertTrue(result.findall('./sets/set[@index="2"]/button[@index="1"]/slots/slot'))

    def test_full_or_unsupported_sets_are_refused_without_editing(self):
        root = ET.fromstring(self.original)
        groups = root.find('sets')
        for index in range(2,9):
            group = ET.SubElement(groups, 'set', {'index':str(index)})
            ET.SubElement(group, 'button', {'index':'1'})
        self.source.write_bytes(ET.tostring(root))
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError,'unused'):
            amx.reserved_profile(self.source,[6])
        self.assertEqual(self.source.read_bytes(),before)
        with self.assertRaisesRegex(ValueError,'distinct'):
            amx.reserved_profile(self.source,[5])

    def test_disabled_preserves_original_path(self):
        self.assertEqual(amx.runtime_profile(self.home,self.rom,self.source), str(self.source))
        self.assertFalse((self.home/'state').exists())

    def test_launcher_switch_stays_empty_until_keyboard_closes(self):
        policy.Settings(self.home).set('on')
        with patch('virtual_keyboard_antimicrox.active_modifiers',return_value=[6]):
            runtime = amx.runtime_profile(self.home,self.rom,self.source)
            state = self.home/'state/virtual-keyboard/profiles'
            marker = state/'visible'
            marker.write_text(json.dumps({'rom':self.rom,'pid':123,'token':'owner'}))
            with patch.object(policy,'process_identity',return_value='owner'):
                second = self.home/'game.amgp'
                second.write_bytes(self.original.replace(b'0x41',b'0x43'))
                shown = amx.runtime_profile(self.home,self.rom,second)
                self.assertEqual(Path(shown).name,'empty.amgp')
                self.assertFalse(ET.parse(shown).findall('.//slot'))
                latest = json.loads((state/'requested').read_text())['profile']
                self.assertNotEqual(latest,runtime)
                self.assertIn(b'0x43',Path(latest).read_bytes())
            with patch.object(policy,'process_identity',return_value=''):
                self.assertEqual(amx.runtime_profile(self.home,self.rom,self.source),runtime)
            marker.unlink()
            self.assertEqual(amx.runtime_profile(self.home,self.rom,self.source),runtime)
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_evdev_priority_never_reloads_profiles_or_waits_on_amx_lock(self):
        with patch.object(amx,'evdev_session',return_value=True), patch.object(amx.subprocess,'run') as run:
            amx.priority(self.home,self.rom,True)
            amx.priority(self.home,self.rom,False)
            run.assert_not_called()
        self.assertFalse((self.home/'state').exists())

    def test_fast_capture_requires_the_current_owned_process_and_backend(self):
        state = self.home/'state/antimicrox'; state.mkdir(parents=True)
        (state/'session').write_text(f'{self.rom}\t123\tstamp\n')
        real_read = Path.read_bytes
        for environment, expected in (
                (b'UWT_AMX_KEYBOARD_EVDEV=1\0SDL_JOYSTICK_HIDAPI=0\0SDL_LINUX_JOYSTICK_CLASSIC=0\0',True),
                (b'UWT_AMX_KEYBOARD_EVDEV=1\0SDL_JOYSTICK_HIDAPI=1\0SDL_LINUX_JOYSTICK_CLASSIC=0\0',False)):
            def read(path):
                return environment if str(path)=='/proc/123/environ' else real_read(path)
            with patch('antimicrox_launcher.Session.active',return_value=True), patch.object(Path,'read_bytes',read):
                self.assertEqual(amx.evdev_session(self.home,self.rom),expected)
                self.assertFalse(amx.evdev_session(self.home,self.rom+'other'))
            with patch('antimicrox_launcher.Session.active',return_value=False), patch.object(Path,'read_bytes',read):
                self.assertFalse(amx.evdev_session(self.home,self.rom))

    def test_priority_only_commands_owned_session_and_restores_latest_profile(self):
        policy.Settings(self.home).set('on')
        with patch('virtual_keyboard_antimicrox.active_modifiers',return_value=[6]):
            runtime = amx.runtime_profile(self.home,self.rom,self.source)
        state = self.home/'state/antimicrox'; state.mkdir(parents=True)
        (state/'session').write_text(f'{self.rom}\t123\tstamp\n')
        with patch('antimicrox_launcher.Session.active',return_value=True), patch.object(amx.subprocess,'run') as run:
            amx.priority(self.home,self.rom,True)
            self.assertEqual(Path(run.call_args.args[0][-1]).name,'empty.amgp')
            amx.priority(self.home,self.rom,False)
            self.assertEqual(run.call_args.args[0][-1],runtime)
        with patch('antimicrox_launcher.Session.active',return_value=False), patch.object(amx.subprocess,'run') as run:
            amx.priority(self.home,self.rom,True)
            run.assert_not_called()

if __name__ == '__main__': unittest.main()
