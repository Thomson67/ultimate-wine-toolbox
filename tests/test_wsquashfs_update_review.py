"""Regressions at update relaunch, native save setup and interrupted compression."""
import json
from pathlib import Path
import shlex
import subprocess
import unittest

import test_wsquashfs_update as fixtures
import v41_savedir

update = fixtures.update
ROOT = Path(__file__).resolve().parents[1]


class UpdateReviewTests(unittest.TestCase):
    setUp = fixtures.UpdateTests.setUp
    prepare = fixtures.UpdateTests.prepare

    def test_retest_restores_newly_selected_directory_from_validated_saves(self):
        update.rewrite_save_rules(self.prefix, '', '')
        self.prepare()
        prepared = self.saves / (self.prefix.stem + '.validated')
        prepared.mkdir()
        (prepared / 'slot.sav').write_text('validated progression')
        location = self.game / 'Saves'
        location.mkdir()
        update.rewrite_save_rules(self.prefix, 'drive_c/game/Saves', '')
        update.prepare_retest(self.manifest, prepared)
        self.assertEqual((location / 'slot.sav').read_text(), 'validated progression')
        self.assertFalse(location.is_symlink())
        self.assertFalse(update.directives(self.prefix)[1].get('SAVEDIR'))
        self.assertEqual((self.original_save / 'slot').read_text(), 'original')
        (location / 'slot.sav').write_text('newer local progression')
        update.prepare_retest(self.manifest, prepared)
        self.assertEqual((location / 'slot.sav').read_text(), 'newer local progression')
        update.restore_live_save_rules(self.manifest, json.loads(self.manifest.read_text()))
        self.assertEqual(update.directives(self.prefix)[1]['SAVEDIR'], 'drive_c/game/Saves')

    def test_retest_of_new_registry_selection_keeps_the_internal_registry(self):
        update.rewrite_save_rules(self.prefix, '', '')
        self.prepare()
        prepared = self.saves / (self.prefix.stem + '.validated')
        prepared.mkdir()
        (prepared / 'user.reg').write_text('validated registry')
        update.rewrite_save_rules(self.prefix, '.', 'user.reg')
        update.prepare_retest(self.manifest, prepared)
        self.assertEqual((self.prefix / 'user.reg').read_text(), 'validated registry')
        self.assertFalse((self.prefix / 'user.reg').is_symlink())
        self.assertFalse(update.directives(self.prefix)[1].get('SAVEFILES'))
        update.restore_live_save_rules(self.manifest, json.loads(self.manifest.read_text()))
        self.assertEqual(update.directives(self.prefix)[1]['SAVEFILES'], 'user.reg')
        self.assertFalse((self.original_save / 'user.reg').exists())

    def test_native_savefiles_resolve_an_internal_profile_alias(self):
        update.rewrite_save_rules(self.prefix, 'drive_c/users/root', 'slot.sav')
        users = self.prefix / 'drive_c/users/steamuser'
        users.mkdir(parents=True)
        (users / 'slot.sav').write_text('embedded old progression')
        (self.original_save / 'slot.sav').write_text('current external progression')
        self.prepare()
        location = self.prefix / 'drive_c/users/root/slot.sav'
        self.assertTrue(location.is_symlink())
        self.assertEqual(location.resolve(), self.original_save / 'slot.sav')
        self.assertEqual(location.read_text(), 'current external progression')
        update.prepare_retest(self.manifest)
        v41_savedir.prepare(self.prefix, self.prefix.name, self.saves)
        self.assertEqual(location.resolve(), self.original_save / 'slot.sav')

    def test_renamed_native_prefix_can_launch_with_the_v41_save_shim(self):
        self.prepare()
        update.prepare_retest(self.manifest)
        v41_savedir.prepare(self.prefix, self.prefix.name, self.saves)
        location = self.prefix / 'drive_c/users/root/Saved'
        self.assertEqual(location.resolve(), self.original_save)

    def test_interrupted_compression_restores_generated_native_links(self):
        self.compression_failure('signal')

    def test_terminal_process_group_closure_restores_generated_native_links(self):
        self.compression_failure('group-signal')

    def test_validation_rejection_restores_generated_native_links(self):
        self.compression_failure('validation')

    def compression_failure(self, failure):
        self.prepare()
        location = self.prefix / 'drive_c/users/root/Saved'
        if failure == 'validation':
            (self.game / 'unknown-save').symlink_to(self.saves / '.uwt-test-unknown')
        state = self.base / 'pending.json'
        log = self.base / 'operation.log'
        state.write_text(json.dumps(dict(phase='testing', metadata=str(self.manifest),
                                         update_log=str(log))))
        q = shlex.quote
        script = f'''
set -u
WT_ROOT={q(str(ROOT / 'toolbox'))}
WT_HOME={q(str(self.base))}
source "$WT_ROOT/modules/wsquashfs.sh"
WSQ_STATE_FILE={q(str(state))}
WSQ_SAVE_ROOT={q(str(self.saves))}
WSQ_CONF={q(str(self.base / 'batocera.conf'))}
i18n() {{ printf '%s' "$1"; }}
msgbox() {{ :; }}
have_dialog() {{ return 1; }}
wt_clear_tty() {{ :; }}
menu_select() {{ printf keep; }}
wsq_update_final_choice() {{ printf replace; }}
maintenance_squash_wine() {{
    [ ! -L {q(str(location))} ] || exit 82
    kill -HUP "$BASHPID"
}}
run_update() {{
    local prefix={q(str(self.prefix))} game_name=Game
    wsq_resume_update
}}
run_update
'''
        if failure == 'group-signal':
            script = script.replace('kill -HUP "$BASHPID"', 'kill -HUP -- "-$$"')
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                timeout=10, start_new_session=True)
        self.assertEqual(result.returncode, -1 if failure == 'group-signal' else 1, result.stderr)
        if failure == 'validation':
            self.assertIn('Temporary save links', log.read_text())
        else:
            self.assertNotIn('Temporary save links', log.read_text())
        self.assertTrue(location.is_symlink(), result.stderr)
        self.assertEqual(location.resolve(), self.original_save)
        self.assertEqual((location / 'slot').read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
