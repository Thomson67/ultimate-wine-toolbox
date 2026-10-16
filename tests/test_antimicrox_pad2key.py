import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
from antimicrox_pad2key import analyze, convert, target_slot
from antimicrox_pad2key_state import Pad2KeyStore
from antimicrox_profiles import Profiles, report
from antimicrox_live import LiveSession

FIXTURES = ROOT/'tests/fixtures/pad2key'


def codes(root, query):
    return [(slot.findtext('mode'), int(slot.findtext('code'), 0)) for slot in root.findall(query+'/slots/slot')]


class Pad2KeyTests(unittest.TestCase):
    def test_native_modifier_sides_and_keypad_enter_keep_linux_uinput_codes(self):
        self.assertEqual(target_slot('KEY_ENTER'), ('keyboard', 0x1000004))
        self.assertEqual(target_slot('KEY_KPENTER'), ('keyboard', 0x60000000+96))
        self.assertEqual(target_slot('KEY_RIGHTCTRL'), ('keyboard', 0x60000000+97))
        self.assertEqual(target_slot('KEY_LEFTCTRL'), ('keyboard', 0x1000021))

    def setup_game(self, folder):
        userdata = Path(folder)/'userdata'; home = userdata/'system/toolbox'
        rom = userdata/'roms/windows/Max Payne [L].wsquashfs'
        rom.parent.mkdir(parents=True); rom.touch()
        keys = Path(str(rom)+'.keys')
        original = (FIXTURES/'max-payne.keys').read_bytes()
        keys.write_bytes(original); keys.chmod(0o640)
        profile = convert(keys, home, userdata=userdata)
        return userdata, home, rom, keys, original, profile, Pad2KeyStore(home, userdata)

    def test_max_payne_every_action_and_snes_button_names(self):
        result = analyze(FIXTURES/'max-payne.keys')
        self.assertEqual((result['converted'], result['total'], result['warnings']), (21, 21, []))
        root = ET.fromstring(result['xml'])
        self.assertEqual(root.tag, 'gamecontroller')
        base = './sets/set'
        expected = {1: 0x1000004, 2: 0x1000001, 3: ord('R'), 4: ord(' '),
                    5: ord('P'), 7: 0x1000000, 8: ord('C'), 9: ord('G'),
                    10: 0x1000017, 11: 0x1000016}
        for index, code in expected.items():
            self.assertEqual(codes(root, base+f'/button[@index="{index}"]'), [('keyboard', code)])
        self.assertEqual(codes(root, base+'/trigger[@index="5"]/triggerbutton'), [('mousebutton', 3)])
        self.assertEqual(codes(root, base+'/trigger[@index="6"]/triggerbutton'), [('mousebutton', 1)])
        for index, key in [(1, 'W'), (3, 'D'), (5, 'S'), (7, 'A')]:
            self.assertEqual(codes(root, base+f'/stick[@index="1"]/stickbutton[@index="{index}"]'), [('keyboard', ord(key))])
        for index, movement in [(1, 1), (3, 4), (5, 2), (7, 3)]:
            self.assertEqual(codes(root, base+f'/stick[@index="2"]/stickbutton[@index="{index}"]'), [('mousemovement', movement)])
        self.assertEqual(len(root.findall(base+'/dpad/dpadbutton')), 4)

    def test_gobliins_left_stick_clicks_and_function_keys(self):
        result = analyze(FIXTURES/'gobliins-6.keys')
        self.assertEqual((result['converted'], result['total'], result['warnings']), (6, 6, []))
        root = ET.fromstring(result['xml']); base = './sets/set'
        self.assertIsNotNone(root.find(base+'/stick[@index="1"]'))
        self.assertIsNone(root.find(base+'/stick[@index="2"]'))
        self.assertEqual(codes(root, base+'/button[@index="1"]'), [('mousebutton', 1)])
        self.assertEqual(codes(root, base+'/button[@index="2"]'), [('mousebutton', 3)])
        self.assertEqual(codes(root, base+'/button[@index="10"]'), [('keyboard', 0x1000036)])
        self.assertEqual(codes(root, base+'/button[@index="11"]'), [('keyboard', 0x1000034)])

    def test_unsupported_actions_reported_and_never_partially_applied_or_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'source.keys'
            source.write_text(json.dumps({'actions_player1': [
                {'trigger': 'b', 'type': 'key', 'target': ['KEY_LEFTCTRL', 'KEY_C']},
                {'trigger': 'a', 'type': 'key', 'target': ['KEY_ENTER', 'KEY_NOT_REAL']},
                {'trigger': ['hotkey', 'b'], 'type': 'key', 'target': 'KEY_ESC'},
                {'trigger': 'x', 'type': 'key', 'target': 'KEY_SPACE', 'hold': 1},
                {'trigger': 'y', 'type': 'exec', 'target': 'touch /never/create'}],
                'actions_player2': [{'trigger': 'b', 'type': 'key', 'target': 'KEY_A'}]}))
            with patch('subprocess.run', side_effect=AssertionError('must not execute')):
                result = analyze(source)
            self.assertEqual(result['converted'], 1)
            self.assertEqual(len(result['warnings']), 5)
            root = ET.fromstring(result['xml'])
            self.assertEqual(codes(root, './sets/set/button[@index="1"]'), [('keyboard', 0x1000021), ('keyboard', ord('C'))])
            self.assertIsNone(root.find('./sets/set/button[@index="2"]'))

    def test_convert_preserves_original_and_existing_profiles_and_preview_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            userdata, home, rom, keys, original, profile, store = self.setup_game(folder)
            before = profile.read_bytes()
            second = convert(keys, home, userdata=userdata)
            self.assertNotEqual(profile, second)
            self.assertEqual(profile.read_bytes(), before)
            self.assertEqual(keys.read_bytes(), original)
            self.assertFalse(store.cfg.exists())
            expected = analyze(keys)['sha256']; keys.write_text('{"actions_player1": []}')
            with self.assertRaisesRegex(ValueError, 'changed'):
                convert(keys, home, expected=expected, userdata=userdata)

    def test_activation_suspends_player_one_and_removal_restores_exact_bytes_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            _, home, rom, keys, original, profile, store = self.setup_game(folder)
            store.assign(str(rom), str(profile))
            self.assertTrue(all(action['target'] == [] for action in json.loads(keys.read_text())['actions_player1']))
            self.assertEqual(store.cfg.read_text(), f'{rom}\t{profile}\n')
            store.assign(str(rom), str(profile))  # idempotent; do not back up the empty overlay
            store.assign(str(rom), '')
            self.assertEqual(keys.read_bytes(), original)
            self.assertEqual(keys.stat().st_mode & 0o777, 0o640)
            self.assertEqual(store.cfg.read_text(), '')
            self.assertEqual(store.read(store.state), {})

    def test_external_pad2key_edits_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, rom, keys, _, profile, store = self.setup_game(folder)
            store.assign(str(rom), str(profile)); cfg = store.cfg.read_bytes()
            keys.write_text('{"actions_player1": [], "actions_player2": []}\n')
            edited = keys.read_bytes()
            with self.assertRaisesRegex(ValueError, 'modified externally'):
                store.assign(str(rom), '')
            self.assertEqual(keys.read_bytes(), edited)
            self.assertEqual(store.cfg.read_bytes(), cfg)
            self.assertIn(str(rom), store.read(store.state))

    def test_reconverted_current_pad2key_is_adopted_and_previous_backup_is_archived(self):
        import base64
        with tempfile.TemporaryDirectory() as folder:
            userdata, home, rom, keys, original, profile, store = self.setup_game(folder)
            store.assign(str(rom), str(profile))
            changed = json.loads(original)
            changed['actions_player1'].append({'trigger': ['hotkey', 'b'], 'type': 'key', 'target': 'KEY_F1'})
            edited = (json.dumps(changed)+'\n').encode(); keys.write_bytes(edited); keys.chmod(0o600)
            replacement = convert(keys, home, userdata=userdata, hotkey='guide')
            archive = store.assign(str(rom), str(replacement))
            record = json.loads(archive.read_text())
            self.assertEqual(base64.b64decode(record['previous_backup']['original']), original)
            self.assertEqual(base64.b64decode(record['new_original']), edited)
            self.assertEqual(base64.b64decode(record['previous_associations']), f'{rom}\t{profile}\n'.encode())
            self.assertEqual(store.cfg.read_text(), f'{rom}\t{replacement}\n')
            self.assertTrue(any(a['trigger'] == ['hotkey', 'b'] and a['target'] == []
                                for a in json.loads(keys.read_text())['actions_player1']))
            self.assertIsNone(store.assign(str(rom), str(replacement)))
            self.assertEqual(len(list(archive.parent.glob('*.json'))), 1)
            store.assign(str(rom), '')
            self.assertEqual(keys.read_bytes(), edited)
            self.assertEqual(keys.stat().st_mode & 0o777, 0o600)
            self.assertTrue(archive.exists())

    def test_recovery_refuses_stale_or_foreign_conversion_without_touching_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            userdata, home, rom, keys, original, profile, store = self.setup_game(folder)
            store.assign(str(rom), str(profile))
            saved = (store.state.read_bytes(), store.cfg.read_bytes())
            changed = json.loads(original); changed['actions_player1'][0]['target'] = 'KEY_F12'
            edited = json.dumps(changed).encode(); keys.write_bytes(edited)
            foreign = Path(folder)/'elsewhere.keys'; foreign.write_bytes(edited)
            replacement = convert(foreign, home, userdata=userdata)
            for selected in (profile, replacement):
                with self.assertRaisesRegex(ValueError, 'changed while suspended'):
                    store.assign(str(rom), str(selected))
                self.assertEqual(keys.read_bytes(), edited)
                self.assertEqual((store.state.read_bytes(), store.cfg.read_bytes()), saved)
            self.assertEqual(list((home/'state').glob('antimicrox-pad2key-recoveries/*.json')), [])

    def test_failed_recovery_assignment_rolls_back_both_backup_generations(self):
        import antimicrox_pad2key_state as state_module
        with tempfile.TemporaryDirectory() as folder:
            userdata, home, rom, keys, original, profile, store = self.setup_game(folder)
            store.assign(str(rom), str(profile))
            changed = json.loads(original); changed['actions_player1'][0]['target'] = 'KEY_F11'
            edited = json.dumps(changed).encode(); keys.write_bytes(edited)
            replacement = convert(keys, home, userdata=userdata)
            before = (store.state.read_bytes(), store.cfg.read_bytes())
            real_atomic = state_module.atomic
            for fail_path in ('archive', 'cfg'):
                failed = []
                def failing(path, *args):
                    if not failed and ((fail_path == 'archive' and path.parent.name == 'antimicrox-pad2key-recoveries')
                                       or (fail_path == 'cfg' and path == store.cfg)):
                        failed.append(True); raise OSError('recovery write failed')
                    return real_atomic(path, *args)
                with patch.object(state_module, 'atomic', side_effect=failing):
                    with self.assertRaises(OSError):
                        store.assign(str(rom), str(replacement))
                self.assertEqual(keys.read_bytes(), edited)
                self.assertEqual((store.state.read_bytes(), store.cfg.read_bytes()), before)
                self.assertEqual(list((home/'state').glob('antimicrox-pad2key-recoveries/*.json')), [])

    def test_recovery_cannot_adopt_a_file_from_an_active_live_session(self):
        with tempfile.TemporaryDirectory() as folder:
            userdata, home, rom, keys, original, profile, store = self.setup_game(folder)
            store.assign(str(rom), str(profile)); keys.write_bytes(original)
            replacement = convert(keys, home, userdata=userdata)
            (home/'state/antimicrox-live.json').write_text(json.dumps({'rom': str(rom), 'phase': 'prepared'}))
            before = store.state.read_bytes()
            with self.assertRaisesRegex(ValueError, 'Finish the live'):
                store.assign(str(rom), str(replacement))
            self.assertEqual(keys.read_bytes(), original)
            self.assertEqual(store.state.read_bytes(), before)

    def test_live_editing_restores_suspended_file_then_unassign_restores_pad2key(self):
        with tempfile.TemporaryDirectory() as folder:
            _, home, rom, keys, original, profile, store = self.setup_game(folder)
            store.assign(str(rom), str(profile)); disabled = keys.read_bytes()
            session = LiveSession(home, rom.parent)
            session.prepare(str(rom), str(profile))
            self.assertEqual(len(json.loads(keys.read_text())['actions_player1']), len(json.loads(disabled)['actions_player1'])+1)
            session.finish('normal'); session.clear()
            self.assertEqual(keys.read_bytes(), disabled)
            store.assign(str(rom), '')
            self.assertEqual(keys.read_bytes(), original)

    def test_deleting_converted_profile_restores_pad2key_and_removes_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            userdata, home, rom, keys, original, profile, store = self.setup_game(folder)
            store.assign(str(rom), str(profile))
            profiles = Profiles(home, userdata, active=lambda: False)
            profiles.delete(profile, profiles.plan(profile)[-1])
            self.assertEqual(keys.read_bytes(), original)
            self.assertFalse(profile.exists())
            self.assertEqual(store.cfg.read_text(), '')
            self.assertNotIn(str(profile), store.read(store.registry))

    def test_failed_assignment_rolls_back_suspension(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, rom, keys, original, profile, store = self.setup_game(folder)
            from antimicrox_pad2key_state import atomic as real_atomic
            def fail_cfg(path, *args):
                if Path(path) == store.cfg: raise OSError('no space')
                return real_atomic(path, *args)
            with patch('antimicrox_pad2key_state.atomic', side_effect=fail_cfg):
                with self.assertRaises(OSError): store.assign(str(rom), str(profile))
            self.assertEqual(keys.read_bytes(), original)
            self.assertFalse(store.cfg.exists())
            self.assertEqual(store.read(store.state), {})

    def test_restore_all_handles_missing_original_and_preserves_other_players(self):
        with tempfile.TemporaryDirectory() as folder:
            userdata, home, rom, keys, _, profile, store = self.setup_game(folder)
            data = json.loads(keys.read_text()); data['actions_player2'] = [{'trigger': 'b', 'type': 'key', 'target': 'KEY_SPACE'}]
            keys.write_text(json.dumps(data)); original = keys.read_bytes()
            profile = convert(keys, home, userdata=userdata)
            store.assign(str(rom), str(profile))
            self.assertEqual(json.loads(keys.read_text())['actions_player2'], data['actions_player2'])
            store.restore_all(); self.assertEqual(keys.read_bytes(), original)
            keys.unlink(); store.assign(str(rom), str(profile)); self.assertTrue(keys.exists())
            store.assign(str(rom), ''); self.assertFalse(keys.exists())

    def test_conversion_live_menu_exits_the_ports_launcher_not_only_a_subshell(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); rom = home/'Game.wsquashfs'; rom.touch()
            Path(str(rom)+'.keys').write_text('{"actions_player1": []}')
            script = '''source "$MODULE"
WT_ROOT="$ROOT/toolbox"
i18n() { echo Retour; }
menu_select() { if [ -f "$WT_HOME/selected" ]; then echo live; else touch "$WT_HOME/selected"; echo game; fi; }
amx_choose_game() { echo "$GAME"; }
amx_pad2key_cmd() { case "$1" in preview) printf 'abc\\nConversion test\\n';; convert) echo "$WT_HOME/profile.amgp";; assign) return 0;; esac; }
have_dialog() { return 1; }
yesno() { return 0; }
amx_running() { return 1; }
amx_live_start_for() { echo started > "$WT_HOME/live"; exit 0; }
amx_convert_pad2key
echo must_not_continue
'''
            result = subprocess.run(['bash', '-c', script], text=True, capture_output=True, timeout=10,
                env=dict(os.environ, WT_HOME=str(home), WT_LANGUAGE='fr', ROOT=str(ROOT), GAME=str(rom), MODULE=str(ROOT/'toolbox/modules/antimicrox.sh')))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((home/'live').exists())
            self.assertNotIn('must_not_continue', result.stdout)
            (home/'selected').unlink()
            (home/'live').unlink()
            file_script = 'set -u\n'+script.replace('echo game;', 'echo file;')
            file_script = file_script.replace('have_dialog() {', 'amx_pad2key_source() { echo "$GAME.keys"; }\nhave_dialog() {')
            result = subprocess.run(['bash', '-c', file_script], text=True, capture_output=True, timeout=10,
                env=dict(os.environ, WT_HOME=str(home), WT_LANGUAGE='fr', ROOT=str(ROOT), GAME=str(rom), MODULE=str(ROOT/'toolbox/modules/antimicrox.sh')))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((home/'live').exists())
            self.assertNotIn('must_not_continue', result.stdout)

    def test_changed_source_cannot_be_activated_without_reconversion(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, rom, keys, _, profile, store = self.setup_game(folder)
            keys.write_text('{"actions_player1": []}')
            with self.assertRaisesRegex(ValueError, 'changed after conversion'):
                store.assign(str(rom), str(profile))
            self.assertEqual(keys.read_text(), '{"actions_player1": []}')
            self.assertFalse(store.cfg.exists())

    def test_mask_overrides_imported_global_triggers_without_emitting_input(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, rom, keys, _, profile, store = self.setup_game(folder)
            original = json.loads(keys.read_text())['actions_player1']
            keys.unlink()  # import can also come from a separate/global .keys file
            store.assign(str(rom), str(profile))
            masks = json.loads(keys.read_text())['actions_player1']
            merged = {}
            # Batocera keeps the first occurrence of each trigger, ROM first.
            for action in masks+original:
                merged.setdefault(action['trigger'], action)
            self.assertEqual(len(merged), len(original))
            self.assertTrue(all(action['type'] == 'key' and action['target'] == [] for action in merged.values()))
            store.assign(str(rom), '')
            self.assertFalse(keys.exists())

    def test_failed_converted_profile_delete_rolls_back_pad2key_and_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            userdata, home, rom, keys, _, profile, store = self.setup_game(folder)
            store.assign(str(rom), str(profile))
            disabled, before = keys.read_bytes(), store.cfg.read_bytes()
            profiles = Profiles(home, userdata, active=lambda: False)
            from antimicrox_profiles import atomic as real_atomic
            def fail_cfg(path, *args):
                if Path(path) == store.cfg: raise OSError('write failed')
                return real_atomic(path, *args)
            with patch('antimicrox_profiles.atomic', side_effect=fail_cfg):
                with self.assertRaises(OSError): profiles.delete(profile, profiles.plan(profile)[-1])
            self.assertTrue(profile.exists())
            self.assertEqual(keys.read_bytes(), disabled)
            self.assertEqual(store.cfg.read_bytes(), before)
            self.assertIn(str(rom), store.read(store.state))

    def test_symlinked_pad2key_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, rom, keys, original, profile, store = self.setup_game(folder)
            target = keys.parent/'external.keys'; target.write_bytes(original)
            keys.unlink(); keys.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                store.assign(str(rom), str(profile))
            self.assertTrue(keys.is_symlink())
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse(store.cfg.exists())

    def test_shared_converted_profile_can_be_enabled_while_source_is_suspended(self):
        with tempfile.TemporaryDirectory() as folder:
            userdata, home, rom, keys, original, profile, store = self.setup_game(folder)
            other = rom.parent/'Other.wsquashfs'; other.touch()
            other_keys = Path(str(other)+'.keys'); other_keys.write_bytes(original)
            store.assign(str(rom), str(profile))
            store.assign(str(other), str(profile))
            profiles = Profiles(home, userdata, active=lambda: False)
            profiles.delete(profile, profiles.plan(profile)[-1])
            self.assertEqual(keys.read_bytes(), original)
            self.assertEqual(other_keys.read_bytes(), original)
            self.assertEqual(store.cfg.read_text(), '')
            self.assertEqual(store.read(store.state), {})

    def test_missing_converted_profile_cannot_suspend_pad2key(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, rom, keys, original, profile, store = self.setup_game(folder)
            profile.unlink()
            with self.assertRaisesRegex(ValueError, 'existing .amgp'):
                store.assign(str(rom), str(profile))
            self.assertEqual(keys.read_bytes(), original)
            self.assertFalse(store.cfg.exists())

    def test_cli_refuses_enabling_conversion_without_working_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            _, home, rom, keys, original, profile, store = self.setup_game(folder)
            from antimicrox_pad2key import main
            with patch.object(sys, 'argv', ['converter', '--home', str(home), 'assign', str(rom), str(profile)]), \
                 patch('antimicrox_pad2key.os.access', return_value=False):
                with self.assertRaisesRegex(ValueError, 'Install AntiMicroX'):
                    main()
            self.assertEqual(keys.read_bytes(), original)
            self.assertFalse(store.cfg.exists())
