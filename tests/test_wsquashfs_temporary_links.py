"""Never republish save links inherited from an interrupted WSquashFS test."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import unittest

import test_wsquashfs_update as fixtures

update = fixtures.update
ROOT = Path(__file__).resolve().parents[1]


class TemporarySaveLinkTests(unittest.TestCase):
    setUp = fixtures.UpdateTests.setUp
    prepare = fixtures.UpdateTests.prepare

    def stale(self, exists=True):
        target = self.saves / '.uwt-test-previous/.legacy-shared/Game'
        if exists:
            target.mkdir(parents=True)
            (target / 'slot').write_text('previous test progression')
        return target

    def link(self, relative, target):
        link = self.prefix / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        return link

    def test_mixed_permanent_and_stale_links_fail_before_move_or_manifest(self):
        (self.prefix / 'autorun.cmd').write_text('DIR=drive_c/game\nCMD=old.exe\n')
        good = self.link('drive_c/game/ph/work/out', self.original_save)
        stale = self.stale()
        bad = self.link('drive_c/users/Public/Documents/Steam/RUNE/534380/remote', stale)
        with self.assertRaisesRegex(ValueError, 'Temporary save links'):
            self.prepare()
        self.assertFalse(self.manifest.exists())
        self.assertTrue(self.source.is_dir())
        self.assertFalse(self.game.with_name('game.bak').exists())
        self.assertEqual(os.readlink(good), str(self.original_save))
        self.assertEqual(os.readlink(bad), str(stale))
        self.assertEqual((stale / 'slot').read_text(), 'previous test progression')

    def test_missing_stale_target_is_also_rejected(self):
        self.link('drive_c/users/Public/save', self.stale(exists=False))
        with self.assertRaisesRegex(ValueError, 'Temporary save links'):
            self.prepare()
        self.assertTrue(self.source.exists())

    def polluted_manifest(self):
        test = self.prepare()
        stale = self.stale()
        link = self.link('drive_c/users/Public/save', test)
        data = json.loads(self.manifest.read_text())
        data['save_links'] = [dict(path=link.relative_to(self.prefix).as_posix(),
                                  original=str(stale), target=str(stale), directory=True)]
        update.save_json(self.manifest, data)
        return test, link

    def test_old_manifest_cannot_restore_stale_links(self):
        test, link = self.polluted_manifest()
        with self.assertRaisesRegex(ValueError, 'Temporary save links'):
            update.restore_legacy(self.prefix, self.manifest)
        self.assertEqual(os.readlink(link), str(test))

    def test_old_manifest_cannot_stage_or_erase_previous_staging(self):
        test, _ = self.polluted_manifest()
        stage = test / '.legacy-publish'; stage.mkdir()
        marker = stage / 'retained'; marker.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'Temporary save links'):
            update.stage_legacy(self.manifest)
        self.assertEqual(marker.read_text(), 'keep')

    def test_final_guard_rejects_current_named_test_and_old_hidden_test(self):
        test = self.prepare()
        link = self.link('drive_c/users/Public/save', test)
        for target in (test, self.stale(exists=False), test / 'missing'):
            link.unlink(); link.symlink_to(target)
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'Temporary save links'):
                update.validate_archive_save_links(self.manifest)

    def test_final_guard_checks_lexical_target_even_through_an_alias(self):
        self.prepare()
        alias = self.saves / '.uwt-test-alias'; alias.symlink_to(self.original_save)
        self.link('drive_c/users/Public/save', alias)
        with self.assertRaisesRegex(ValueError, 'Temporary save links'):
            update.validate_archive_save_links(self.manifest)

    def test_permanent_links_survive_replace_and_backup_cleanup(self):
        (self.prefix / 'autorun.cmd').write_text('DIR=drive_c/game\nCMD=old.exe\n')
        links = [self.link(path, self.original_save) for path in (
            'drive_c/game/ph/work/out', 'drive_c/game/ph/work/bin/x64/SteamData',
            'drive_c/users/Public/Documents/Steam/RUNE/534380/remote',
            'drive_c/users/steamuser/AppData/Roaming/Goldberg/534380/remote')]
        self.prepare()
        (links[0] / 'slot').write_text('tested progression')
        update.finish_game(self.manifest)
        update.stage_legacy(self.manifest)
        update.restore_legacy(self.prefix, self.manifest)
        update.validate_archive_save_links(self.manifest)
        staged = self.base / 'staged'; staged.write_bytes(b'new archive')
        update.commit(self.manifest, staged, keep_archive_backup=False)
        update.cleanup_test_saves(self.manifest)
        update.manage_save_backups(self.manifest, remove=True)
        for link in links:
            self.assertEqual(os.readlink(link), str(self.original_save))
            self.assertEqual((link / 'slot').read_text(), 'tested progression')

    def test_shell_ready_resume_refuses_before_compression(self):
        self.prepare()
        self.link('drive_c/users/Public/save', self.stale(exists=False))
        state = self.base / 'state'; state.mkdir()
        state_file = state / 'pending.json'
        log = self.base / 'update.log'; log.touch()
        state_file.write_text(json.dumps(dict(phase='ready', metadata=str(self.manifest),
                                              update_log=str(log))))
        q = shlex.quote
        script = f'''
WT_ROOT={q(str(ROOT / 'toolbox'))}
WT_HOME={q(str(self.base))}
source "$WT_ROOT/modules/wsquashfs.sh"
WSQ_STATE_FILE={q(str(state_file))}
WSQ_SAVE_ROOT={q(str(self.saves))}
i18n() {{ printf '%s' "$1"; }}
msgbox() {{ :; }}
wsq_update_final_choice() {{ printf replace; }}
maintenance_squash_wine() {{ touch {q(str(self.base / 'compressed'))}; return 1; }}
run_update() {{
    local prefix={q(str(self.prefix))} game_name=Game
    wsq_resume_update
}}
run_update
'''
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse((self.base / 'compressed').exists())
        self.assertIn('Temporary save links', log.read_text())
        self.assertEqual(self.archive.read_bytes(), b'old archive')


if __name__ == '__main__':
    unittest.main()
