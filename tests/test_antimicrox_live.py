import copy
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
spec = importlib.util.spec_from_file_location('amx_live', ROOT/'toolbox/helpers/antimicrox_live.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class LiveSessionTests(unittest.TestCase):
    def test_result_receipt_retires_only_antimicrox_request_and_keeps_profile_recoverable(self):
        for marker in (b'antimicrox\n', b'reshade\n', b''):
            with self.subTest(marker=marker):
                data = self.session.prepare(self.rom)
                self.session.finish('normal')
                request = self.home/'state/resume-wsq.request'
                request.write_bytes(marker)
                self.session.acknowledge_return()
                self.assertTrue(self.session.read()['return_presented'])
                self.assertTrue(Path(data['profile']).is_file())
                self.assertFalse(self.keys.exists())
                self.assertFalse(self.session.request_return(str(self.rom), data['session_id']))
                if marker == b'antimicrox\n': self.assertFalse(request.exists())
                else: self.assertEqual(request.read_bytes(), marker)
                request.unlink(missing_ok=True)
                self.session.clear()

    def test_receipt_requires_successful_shortcut_restoration(self):
        self.session.prepare(self.rom)
        with self.assertRaises(ValueError):
            self.session.acknowledge_return()
        self.assertTrue(self.keys.exists())
        self.assertNotIn('return_presented', self.session.read())

    def test_old_worker_cannot_request_return_for_a_new_session_or_replace_foreign_request(self):
        data = self.session.prepare(self.rom)
        self.session.finish('normal')
        self.session.clear()
        new = self.session.prepare(self.rom)
        self.assertNotEqual(data['session_id'], new['session_id'])
        self.assertFalse(self.session.request_return(str(self.rom), data['session_id']))
        request = self.home/'state/resume-wsq.request'
        request.write_bytes(b'reshade\n')
        self.assertFalse(self.session.request_return(str(self.rom), new['session_id']))
        self.assertEqual(request.read_bytes(), b'reshade\n')

    def test_hup_at_finished_menu_does_not_leave_an_automatic_return_pending(self):
        data = self.session.prepare(self.rom)
        self.session.finish('normal')
        request = self.home/'state/resume-wsq.request'
        request.write_bytes(b'antimicrox\n')
        fake_root = self.base/'toolbox'
        (fake_root/'hooks').mkdir(parents=True)
        (fake_root/'hooks/antimicrox-game-event.sh').write_text('#!/bin/bash\nexit 0\n')
        script = r'''
source "$MODULE"
MAIN_PID=$$
amx_live_cmd() { python3 "$HELPER" --home "$WT_HOME" "$@"; }
amx_txt() { printf '%s' "$1"; }
i18n() { printf '%s' "$1"; }
menu_select() { touch "$WT_HOME/menu-shown"; kill -HUP "$MAIN_PID"; }
amx_live_resume
'''
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=10,
            env=dict(os.environ, WT_HOME=str(self.home), WT_ROOT=str(fake_root), WT_LANGUAGE='fr',
                     MODULE=str(ROOT/'toolbox/modules/antimicrox.sh'), HELPER=str(ROOT/'toolbox/helpers/antimicrox_live.py')))
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home/'menu-shown').exists(), result.stderr)
        self.assertTrue(self.session.read()['return_presented'])
        self.assertFalse(request.exists())
        self.assertTrue(Path(data['profile']).exists())
        self.assertFalse(self.session.request_return(str(self.rom), data['session_id']))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.rom_root = self.base/'windows'; self.rom_root.mkdir()
        self.rom = self.rom_root/'My Game[GE Proton].wine'; self.rom.mkdir()
        self.home = self.base/'home'
        self.session = live.LiveSession(self.home, self.rom_root)
        self.keys = self.rom/'padto.keys'

    def test_new_session_creates_profile_and_temporary_shortcut_then_removes_keys(self):
        data = self.session.prepare(self.rom)
        self.assertTrue(live.valid_profile(data['profile']))
        self.assertEqual(json.loads(self.keys.read_text())['actions_player1'], [data['action']])
        self.assertEqual(data['action']['type'], 'exec')
        self.assertEqual(data['action']['trigger'], live.ACTION['trigger'])
        command = shlex.split(data['action']['target'])
        self.assertEqual(command[:7], ['python3', str(self.home/'toolbox/helpers/antimicrox_focus.py'),
                                      'toggle', '--home', str(self.home), '--session-id', data['session_id']])
        self.assertEqual(self.session.profile(str(self.rom)), data['profile'])
        self.session.finish('normal')
        self.assertFalse(self.keys.exists())
        self.assertEqual(self.session.read()['phase'], 'finished')
        self.session.clear()
        self.assertFalse(self.session.state.exists())
        self.assertTrue(Path(data['profile']).exists())

    def test_existing_keys_are_restored_byte_for_byte_with_their_mode(self):
        raw = b'{"actions_player1": [{"trigger":"a","type":"key","target":"KEY_ESC"}]}\n'
        self.keys.write_bytes(raw); self.keys.chmod(0o640)
        self.session.prepare(self.rom)
        self.session.finish()
        self.assertEqual(self.keys.read_bytes(), raw)
        self.assertEqual(self.keys.stat().st_mode & 0o777, 0o640)

    def test_same_chord_is_overridden_without_duplicates_and_restored(self):
        old = {'trigger': ['pagedown', 'hotkey'], 'type': 'key', 'target': []}
        self.keys.write_text(json.dumps({'actions_player1': [old]}))
        data = self.session.prepare(self.rom)
        self.assertEqual(json.loads(self.keys.read_text())['actions_player1'], [data['action']])
        self.session.finish()
        self.assertEqual(json.loads(self.keys.read_text())['actions_player1'], [old])

    def test_concurrent_unrelated_edits_survive_restoration(self):
        old = {'trigger': ['hotkey', 'pagedown'], 'type': 'key', 'target': []}
        new = {'trigger': 'x', 'type': 'key', 'target': 'KEY_SPACE'}
        self.keys.write_text(json.dumps({'actions_player1': [old]}))
        self.session.prepare(self.rom)
        current = json.loads(self.keys.read_text()); current['actions_player1'].append(new)
        self.keys.write_text(json.dumps(current))
        self.session.finish()
        self.assertEqual(json.loads(self.keys.read_text())['actions_player1'], [new, old])

    def test_concurrent_replacement_of_same_chord_is_preserved(self):
        self.session.prepare(self.rom)
        replacement = dict(live.ACTION, target='KEY_F1', description='user rule')
        self.keys.write_text(json.dumps({'actions_player1': [replacement]}))
        self.session.finish()
        self.assertEqual(json.loads(self.keys.read_text())['actions_player1'], [replacement])

    def test_direct_switch_command_quotes_home_and_has_a_new_session_token(self):
        home = self.base/"home with spaces ' $(echo bad)"
        session = live.LiveSession(home, self.rom_root)
        first = session.prepare(self.rom)
        command = shlex.split(first['action']['target'])
        self.assertEqual(command[1], str(home/'toolbox/helpers/antimicrox_focus.py'))
        self.assertEqual(command[4], str(home))
        self.assertEqual(command[6], first['session_id'])
        session.finish(); session.clear()
        second = session.prepare(self.rom)
        self.assertNotEqual(first['session_id'], second['session_id'])

    def test_invalid_existing_json_is_not_overwritten(self):
        self.keys.write_text('broken json')
        with self.assertRaises(ValueError): self.session.prepare(self.rom)
        self.assertEqual(self.keys.read_text(), 'broken json')
        self.assertFalse(self.session.state.exists())

    def test_symlinked_keys_are_not_replaced(self):
        target = self.base/'original'; target.write_text('{}')
        self.keys.symlink_to(target)
        with self.assertRaises(ValueError): self.session.prepare(self.rom)
        self.assertTrue(self.keys.is_symlink())
        self.assertEqual(target.read_text(), '{}')

    def test_one_session_at_a_time_and_clear_requires_restoration(self):
        self.session.prepare(self.rom)
        with self.assertRaises(ValueError): self.session.prepare(self.rom)
        with self.assertRaises(ValueError): self.session.clear()
        self.assertEqual(self.session.profile('different-game'), '')

    def test_wsquashfs_uses_adjacent_keys_without_changing_archive(self):
        rom = self.rom_root/'Compressed.wsquashfs'; rom.write_bytes(b'archive unchanged')
        data = self.session.prepare(rom)
        self.assertEqual(data['keys'], str(rom)+'.keys')
        self.session.finish()
        self.assertFalse(Path(data['keys']).exists())
        self.assertEqual(rom.read_bytes(), b'archive unchanged')

    def test_recovery_after_prepared_state_and_repeated_finish_is_safe(self):
        self.session.prepare(self.rom)
        fresh = live.LiveSession(self.home, self.rom_root)
        fresh.finish('recovered'); fresh.finish('ignored')
        self.assertFalse(self.keys.exists())
        self.assertEqual(fresh.read()['result'], 'recovered')

    def test_profile_error_does_not_inject_shortcut(self):
        profile = self.home/'bad.amgp'; profile.parent.mkdir(); profile.write_text('<invalid/>')
        with self.assertRaises(ValueError): self.session.prepare(self.rom, profile)
        self.assertFalse(self.keys.exists())
        self.assertFalse(self.session.state.exists())

    def test_original_profile_is_reused_without_changing_contents(self):
        profile = self.home/'Existing profile.amgp'; profile.parent.mkdir()
        profile.write_text('<joystick configversion="19"><sets/></joystick>')
        before = profile.read_bytes()
        data = self.session.prepare(self.rom, profile)
        self.assertEqual(data['profile'], str(profile))
        self.assertEqual(profile.read_bytes(), before)

    def test_failed_restore_retains_backup_and_allows_retry(self):
        self.keys.write_text('{"actions_player1": []}')
        self.session.prepare(self.rom)
        self.keys.write_text('malformed concurrent edit')
        with self.assertRaises(ValueError): self.session.finish()
        self.assertIsNotNone(self.session.read()['original'])
        self.assertNotEqual(self.session.read()['phase'], 'finished')


class LivePortTests(unittest.TestCase):
    def test_live_monitor_restores_shortcut_without_touching_wsq_result(self):
        source = (ROOT/'toolbox/ports/Ultimate Wine Toolbox.sh').read_text()
        function = source.split('monitor_wsq_launch() {', 1)[1].split('\nresume_wsq_unavailable() {', 1)[0]
        for success in [True, False]:
            with self.subTest(success=success), tempfile.TemporaryDirectory() as folder:
                base = Path(folder); (base/'live').touch(); (base/'result').write_text('wsq pending')
                script = 'monitor_wsq_launch() {'+function+'''
launch_game_via_es() { return "$LAUNCH_RC"; }
wait_for_game_start() { GAME_STARTED_AT=$((SECONDS-40)); }
wait_for_game_stop() { return 0; }
finish_amx_live() { printf '%s' "$1" > "$TEST_DIR/finished"; }
resume_wsquashfs_toolbox() { touch "$TEST_DIR/resumed"; }
monitor_wsq_launch
'''
                env = dict(os.environ, TEST_DIR=folder, AMX_REQUEST=str(base/'live'),
                           RESULT_FILE=str(base/'result'), DIAG_REQUEST=str(base/'no-diagnostic'),
                           BOOT_LOG=str(base/'log'), launch_rom='/games/Game.wine', LAUNCH_RC='0' if success else '1')
                result = subprocess.run(['bash', '-u', '-c', script], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((base/'result').read_text(), 'wsq pending')
                self.assertEqual((base/'finished').read_text(), 'normal' if success else 'launch_failed')
                self.assertTrue((base/'resumed').exists())

    def test_resume_dispatches_to_antimicrox(self):
        source = (ROOT/'toolbox/ports/Ultimate Wine Toolbox.sh').read_text()
        function = source.split('resume_wsquashfs_toolbox() {', 1)[1].split('\nlaunch_rom=""', 1)[0]
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); (base/'live').touch()
            script = 'resume_wsquashfs_toolbox() {'+function+'''
wait_for_es_api() { return 0; }
launch_game_via_es() { printf '%s' "$RESUME_ENV" > "$TEST_DIR/env"; }
python3() { printf '%s' "$RESUME_ENV" > "$TEST_DIR/env"; }
resume_wsquashfs_toolbox
'''
            env = dict(os.environ, TEST_DIR=folder, AMX_REQUEST=str(base/'live'),
                       RESUME_REQUEST=str(base/'resume'), DIAG_REQUEST=str(base/'none'),
                       BOOT_LOG=str(base/'log'), TOOLBOX_PORT='/ports/Toolbox.sh')
            result = subprocess.run(['bash', '-u', '-c', script], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((base/'env').read_text(), 'WT_AUTO_RESUME_AMX')
            self.assertEqual((base/'resume').read_text(), 'antimicrox\n')


if __name__ == '__main__':
    unittest.main()
