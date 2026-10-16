import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
from antimicrox_hotkey import choices
from antimicrox_pad2key import analyze, convert, summary
from antimicrox_pad2key_state import Pad2KeyStore
import antimicrox_live as live
from unittest.mock import patch


class HotkeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base/'source.keys'

    def analyze(self, actions, hotkey='guide'):
        self.source.write_text(json.dumps({'actions_player1': actions}))
        result = analyze(self.source, hotkey)
        return result, ET.fromstring(result['xml'])

    def key(self, trigger, key):
        return {'trigger': trigger, 'type': 'key', 'target': key}

    def codes(self, root, group, path):
        return [int(slot.findtext('code'), 0) for slot in root.findall(f'./sets/set[@index="{group}"]/{path}/slots/slot')]

    def test_hotkey_switches_sets_while_held_with_explicit_return(self):
        result, root = self.analyze([self.key(['hotkey', 'b'], ['KEY_LEFTCTRL', 'KEY_C'])])
        self.assertEqual((result['converted'], result['chords'], result['warnings']), (1, 1, []))
        for group, target in [(1, '2'), (2, '1')]:
            button = root.find(f'./sets/set[@index="{group}"]/button[@index="6"]')
            self.assertEqual(button.findtext('setselect'), target)
            self.assertEqual(button.findtext('setselectcondition'), 'while-held')
        self.assertEqual(self.codes(root, 1, 'button[@index="1"]'), [])
        self.assertEqual(self.codes(root, 2, 'button[@index="1"]'), [0x1000021, ord('C')])
        self.assertIn('Hotkey + Start', summary(result))

    def test_ordinary_actions_remain_and_chord_adds_its_output_like_evmapy(self):
        _, root = self.analyze([self.key('b', 'KEY_ENTER'), self.key('a', 'KEY_SPACE'),
                               self.key(['b', 'hotkey'], 'KEY_F1')])
        self.assertEqual(self.codes(root, 1, 'button[@index="1"]'), [0x1000004])
        self.assertEqual(self.codes(root, 2, 'button[@index="1"]'), [0x1000004, 0x1000030])
        self.assertEqual(self.codes(root, 2, 'button[@index="2"]'), [ord(' ')])

    def test_hotkey_start_never_inherits_plain_start_but_explicit_chord_is_allowed(self):
        actions = [self.key('start', 'KEY_ESC'), self.key(['hotkey', 'b'], 'KEY_F2')]
        _, root = self.analyze(actions)
        self.assertEqual(self.codes(root, 1, 'button[@index="7"]'), [0x1000000])
        self.assertIsNone(root.find('./sets/set[@index="2"]/button[@index="7"]'))
        actions.append(self.key(['start', 'hotkey'], 'KEY_F5'))
        result, root = self.analyze(actions)
        self.assertEqual(result['converted'], 3)
        self.assertEqual(self.codes(root, 2, 'button[@index="7"]'), [0x1000000, 0x1000034])

    def test_chords_support_dpad_trigger_and_stick_directions(self):
        result, root = self.analyze([self.key(['hotkey', 'left'], 'KEY_LEFT'),
                                    self.key(['r2', 'hotkey'], 'BTN_RIGHT'),
                                    self.key(['hotkey', 'joystick1up'], 'KEY_W')], 'select')
        self.assertEqual(result['converted'], 3)
        self.assertEqual(root.findtext('./sets/set/button[@index="5"]/setselect'), '2')
        self.assertEqual(self.codes(root, 2, 'dpad/dpadbutton[@index="8"]'), [0x1000012])
        self.assertEqual(self.codes(root, 2, 'trigger[@index="6"]/triggerbutton'), [3])
        self.assertEqual(self.codes(root, 2, 'stick/stickbutton[@index="1"]'), [ord('W')])

    def test_unknown_modifier_complex_chords_hold_and_bad_keys_are_reported_atomically(self):
        actions = [self.key(['hotkey', 'b'], 'KEY_F1')]
        result, root = self.analyze(actions, None)
        self.assertEqual(result['converted'], 0)
        self.assertIn('Select the Batocera Hotkey', result['warnings'][0])
        actions += [self.key(['hotkey', 'a', 'x'], 'KEY_F2'),
                    {**self.key(['hotkey', 'a'], 'KEY_F2'), 'hold': 1},
                    self.key(['hotkey', 'x'], ['KEY_C', 'KEY_NOT_REAL'])]
        result, root = self.analyze(actions)
        self.assertEqual((result['converted'], result['chords']), (1, 1))
        self.assertEqual(len(result['warnings']), 3)
        self.assertIsNone(root.find('./sets/set[@index="2"]/button[@index="4"]'))

    def test_modifier_and_chord_cannot_resolve_to_same_button(self):
        result, root = self.analyze([self.key(['hotkey', 'select'], 'KEY_F1')], 'select')
        self.assertEqual(result['converted'], 0)
        self.assertEqual(len(root.findall('./sets/set')), 1)
        with self.assertRaises(ValueError): self.analyze([], 'start')

    def test_normal_profiles_do_not_gain_sets_or_modifier_assignments(self):
        _, root = self.analyze([self.key('start', 'KEY_ESC')])
        self.assertEqual(len(root.findall('./sets/set')), 1)
        self.assertEqual(root.findall('.//setselect'), [])

    def test_alias_resolution_uses_configured_button_and_user_settings_override_system(self):
        user = self.base/'user.xml'; system = self.base/'system.xml'
        config = '<inputConfig type="joystick" deviceGUID="abc" deviceName="Pad"><input name="hotkey" type="button" id="8"/><input name="select" type="button" id="8"/></inputConfig>'
        user.write_text('<inputList>'+config+'</inputList>')
        system.write_text('<inputList>'+config.replace('id="8"/>', 'id="9"/>', 1)+'</inputList>')
        self.assertEqual(choices([user, system]), [('select', 'Pad')])
        self.assertEqual(choices([system]), [('guide', 'Pad')])

    def test_ambiguous_or_axis_hotkeys_are_not_guessed(self):
        config = self.base/'input.xml'
        for extra, kind in [('<input name="start" type="button" id="8"/>', 'button'), ('', 'axis')]:
            config.write_text(f'<inputList><inputConfig type="joystick"><input name="hotkey" type="{kind}" id="8"/>{extra}</inputConfig></inputList>')
            self.assertEqual(choices([config]), [])

    def test_activation_keeps_es_kill_chord_unmasked_unless_it_exists_in_source(self):
        userdata = self.base/'userdata'; home = userdata/'system/uwt'
        rom = userdata/'roms/windows/Game.wsquashfs'; rom.parent.mkdir(parents=True); rom.touch()
        source = Path(str(rom)+'.keys')
        original = {'actions_player1': [self.key('start', 'KEY_ESC'), self.key(['hotkey', 'b'], 'KEY_F1')]}
        source.write_text(json.dumps(original))
        profile = convert(source, home, userdata=userdata, hotkey='guide')
        store = Pad2KeyStore(home, userdata); store.assign(str(rom), str(profile))
        masks = json.loads(source.read_text())['actions_player1']
        self.assertFalse(any(isinstance(a['trigger'], list) and set(a['trigger']) == {'hotkey', 'start'} for a in masks))
        metadata = store.read(store.registry)[str(profile.resolve())]
        self.assertEqual((metadata['hotkey'], metadata['chords']), ('guide', 1))
        store.assign(str(rom), '')
        self.assertEqual(json.loads(source.read_text()), original)

    def test_live_prefers_r1_and_leaves_converted_hotkey_a_untouched(self):
        result, _ = self.analyze([self.key(['hotkey', 'b'], 'KEY_F1')])
        profile = self.base/'profile.amgp'; profile.write_bytes(result['xml'])
        with patch.object(live, 'hotkey_choices', return_value=[]):
            action, fr, en = live.switch_for(profile, self.base)
        self.assertEqual(action['trigger'], ['hotkey', 'pagedown'])
        self.assertIn('R1', fr)
        self.assertEqual(profile.read_bytes(), result['xml'])

    def test_live_uses_select_if_r1_chord_is_mapped_and_keyboard_if_both_are(self):
        profile = self.base/'profile.amgp'
        actions = [self.key(['hotkey', 'pagedown'], 'KEY_F1')]
        with patch.object(live, 'hotkey_choices', return_value=[]):
            result, _ = self.analyze(actions); profile.write_bytes(result['xml'])
            self.assertEqual(live.switch_for(profile, self.base)[0]['trigger'], ['hotkey', 'select'])
            actions.append(self.key(['hotkey', 'select'], 'KEY_F2'))
            result, _ = self.analyze(actions); profile.write_bytes(result['xml'])
            self.assertIsNone(live.switch_for(profile, self.base)[0])

    def test_live_never_uses_hotkey_button_itself_or_occupied_pad2key_shortcut(self):
        result, _ = self.analyze([self.key('b', 'KEY_ENTER')])
        profile = self.base/'profile.amgp'; profile.write_bytes(result['xml'])
        with patch.object(live, 'hotkey_choices', return_value=[('pagedown', 'Pad')]):
            self.assertEqual(live.switch_for(profile, self.base)[0]['trigger'], ['hotkey', 'select'])
        with patch.object(live, 'hotkey_choices', return_value=[]):
            self.assertIsNone(live.switch_for(profile, self.base, [self.key(['hotkey', 'pagedown'], 'KEY_F1'),
                                                                self.key(['hotkey', 'select'], 'KEY_F2')])[0])

    def test_fallback_shortcut_and_concurrent_edits_are_restored_without_touching_profile(self):
        home = self.base/'home'; roms = self.base/'windows'; roms.mkdir()
        rom = roms/'Game.wine'; rom.mkdir()
        keys = rom/'padto.keys'; keys.write_bytes(b'{}\n')
        result, _ = self.analyze([self.key(['hotkey', 'pagedown'], 'KEY_F1')])
        home.mkdir(); profile = home/'profile.amgp'; profile.write_bytes(result['xml'])
        session = live.LiveSession(home, roms)
        with patch.object(live, 'hotkey_choices', return_value=[]):
            data = session.prepare(rom, profile)
        self.assertEqual(data['action']['trigger'], ['hotkey', 'select'])
        config = json.loads(keys.read_text()); config['actions_player1'].append(self.key('x', 'KEY_SPACE'))
        keys.write_text(json.dumps(config))
        session.finish()
        self.assertEqual(json.loads(keys.read_text())['actions_player1'], [self.key('x', 'KEY_SPACE')])
        self.assertEqual(profile.read_bytes(), result['xml'])

    def test_legacy_alt_tab_shortcut_is_cleaned_up_after_concurrent_edits(self):
        home = self.base/'home'; roms = self.base/'windows'; roms.mkdir()
        rom = roms/'Game.wine'; rom.mkdir()
        session = live.LiveSession(home, roms)
        with patch.object(live, 'hotkey_choices', return_value=[]):
            data = session.prepare(rom)
        data.pop('action'); session.write(data)
        keys = Path(data['keys'])
        extra = self.key('x', 'KEY_SPACE')
        keys.write_text(json.dumps({'actions_player1': [live.LEGACY_ACTION, extra]}))
        session.finish()
        self.assertEqual(json.loads(keys.read_text())['actions_player1'], [extra])

    def test_conversion_menu_uses_same_detected_hotkey_for_preview_and_creation(self):
        script = r'''
set -u
source "$ROOT/toolbox/modules/antimicrox.sh"
WT_ROOT="$ROOT/toolbox"
i18n() { echo Back; }
menu_select() { if [ -f "$WT_HOME/chosen" ]; then echo back; else touch "$WT_HOME/chosen"; echo file; fi; }
amx_pad2key_source() { echo "$WT_HOME/source.keys"; }
amx_pad2key_cmd() {
  case "$1" in
    hotkeys) printf 'guide\tPad Guide\n';;
    preview) printf '%s\n' "$*" > "$WT_HOME/preview-args"; printf 'hash\nPreview\n';;
    convert) printf '%s\n' "$*" > "$WT_HOME/convert-args"; echo "$WT_HOME/profile.amgp";;
  esac
}
have_dialog() { return 1; }
yesno() { return 0; }
amx_convert_pad2key
'''
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                env=dict(os.environ, ROOT=str(ROOT), WT_HOME=str(self.base), WT_LANGUAGE='fr'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--hotkey guide', (self.base/'preview-args').read_text())
        self.assertIn('--expected hash --hotkey guide', (self.base/'convert-args').read_text())

    def test_keyboard_only_session_injects_no_controller_chord_and_restores_bytes(self):
        home = self.base/'home'; home.mkdir()
        roms = self.base/'windows'; roms.mkdir(); rom = roms/'Game.wine'; rom.mkdir()
        keys = rom/'padto.keys'; original = b'{}\n'; keys.write_bytes(original)
        result, _ = self.analyze([self.key(['hotkey', 'pagedown'], 'KEY_F1'),
                                  self.key(['hotkey', 'select'], 'KEY_F2')])
        profile = home/'profile.amgp'; profile.write_bytes(result['xml'])
        session = live.LiveSession(home, roms)
        with patch.object(live, 'hotkey_choices', return_value=[]):
            data = session.prepare(rom, profile)
        self.assertIsNone(data['action'])
        self.assertEqual(json.loads(keys.read_text())['actions_player1'], [])
        self.assertIn('uniquement', data['switch_fr'])
        session.finish()
        self.assertEqual(keys.read_bytes(), original)


if __name__ == '__main__': unittest.main()
