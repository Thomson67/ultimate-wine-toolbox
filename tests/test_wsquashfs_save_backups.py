"""Only explicitly confirmed backups from the successful current update may go."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import test_wsquashfs_update as fixtures

update = fixtures.update
ROOT = Path(__file__).resolve().parents[1]


class SaveBackupTests(unittest.TestCase):
    setUp = fixtures.UpdateTests.setUp
    prepare = fixtures.UpdateTests.prepare

    def publish(self, extra=False):
        self.prepare()
        if extra:
            target = self.saves/'Other save'; target.mkdir(); (target/'slot').write_text('old extra')
            prepared = self.saves/'extra-prepared'; prepared.mkdir(); (prepared/'slot').write_text('new extra')
            data = json.loads(self.manifest.read_text())
            data['legacy_publish'] = [{'target': str(target), 'prepared': str(prepared)}]
            update.save_json(self.manifest, data)
        prepared = self.saves/'validated'; prepared.mkdir(); (prepared/'slot').write_text('tested progression')
        staged = self.base/'new.wsquashfs'; staged.write_bytes(b'new archive')
        self.archive_backup = update.commit(self.manifest, staged, prepared)
        return update.manage_save_backups(self.manifest)

    def test_confirmed_cleanup_only_removes_this_operations_save_backups(self):
        old = self.saves/'Game.backup-20000101-000000-000001'; old.mkdir(); (old/'slot').write_text('older')
        backups = self.publish()
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0]/'slot').read_text(), 'original')
        update.manage_save_backups(self.manifest, remove=True)
        self.assertFalse(backups[0].exists())
        self.assertEqual((self.original_save/'slot').read_text(), 'tested progression')
        self.assertTrue(old.is_dir()); self.assertEqual(self.archive_backup.read_bytes(), b'old archive')
        self.assertEqual(update.manage_save_backups(self.manifest, remove=True), [])

    def test_all_legacy_backups_are_recorded_not_only_the_last_one(self):
        backups = self.publish(extra=True)
        self.assertEqual(len(backups), 2)
        data = json.loads(self.manifest.read_text())
        self.assertEqual(len(data['save_backups']), 2)
        update.manage_save_backups(self.manifest, remove=True)
        self.assertTrue(all(not p.exists() for p in backups))
        self.assertEqual((self.saves/'Other save/slot').read_text(), 'new extra')

    def test_keep_choice_preserves_backups_and_is_persisted(self):
        backups = self.publish(); update.manage_save_backups(self.manifest, keep=True)
        self.assertTrue(all(p.is_dir() for p in backups))
        self.assertEqual(json.loads(self.manifest.read_text())['save_backup_choice'], 'keep')

    def test_uncommitted_state_cannot_delete_backups(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'committed'):
            update.manage_save_backups(self.manifest, remove=True)
        self.assertEqual((self.original_save/'slot').read_text(), 'original')

    def test_missing_active_save_preserves_its_backup(self):
        backups = self.publish(); shutil.rmtree(self.original_save)
        with self.assertRaisesRegex(ValueError, 'missing'):
            update.manage_save_backups(self.manifest, remove=True)
        self.assertTrue(backups[0].exists())

    def test_replaced_active_save_preserves_backup(self):
        backups = self.publish(); self.original_save.rename(self.saves/'retained-active')
        self.original_save.mkdir()
        with self.assertRaisesRegex(ValueError, 'destination changed'):
            update.manage_save_backups(self.manifest, remove=True)
        self.assertTrue(backups[0].exists())

    def test_edits_inside_a_nested_backup_directory_block_cleanup(self):
        self.prepare()
        nested=self.original_save/'nested'; nested.mkdir(); (nested/'save').write_text('old')
        staged=self.base/'new.wsquashfs'; staged.write_bytes(b'new')
        prepared=self.saves/'validated'; prepared.mkdir()
        update.commit(self.manifest, staged, prepared)
        backup=update.manage_save_backups(self.manifest)[0]
        (backup/'nested/save').write_text('manual recovery data')
        with self.assertRaisesRegex(ValueError, 'backup changed'):
            update.manage_save_backups(self.manifest, remove=True)
        self.assertEqual((backup/'nested/save').read_text(), 'manual recovery data')

    def test_symlink_replacement_is_refused_without_following_it(self):
        backups=self.publish(); backup=backups[0]; backup.rename(self.saves/'retained-original')
        outside=self.base/'external'; outside.mkdir(); (outside/'save').write_text('external')
        backup.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            update.manage_save_backups(self.manifest, remove=True)
        self.assertEqual((outside/'save').read_text(), 'external')

    def test_all_records_are_validated_before_any_deletion(self):
        backups=self.publish(extra=True); data=json.loads(self.manifest.read_text())
        data['save_backups'][-1]['path']=str(self.original_save)
        update.save_json(self.manifest,data)
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            update.manage_save_backups(self.manifest, remove=True)
        self.assertTrue(all(p.exists() for p in backups))

    def test_old_manifest_does_not_infer_paths_from_single_legacy_backup(self):
        backups=self.publish(extra=True); data=json.loads(self.manifest.read_text())
        data.pop('save_backups'); update.save_json(self.manifest,data)
        self.assertEqual(update.manage_save_backups(self.manifest, remove=True), [])
        self.assertTrue(all(p.exists() for p in backups))

    def test_link_inside_backup_is_unlinked_without_deleting_its_target(self):
        self.prepare(); outside=self.base/'external'; outside.mkdir(); (outside/'save').write_text('external')
        (self.original_save/'link').symlink_to(outside,target_is_directory=True)
        prepared=self.saves/'validated'; prepared.mkdir()
        staged=self.base/'new.wsquashfs'; staged.write_bytes(b'new')
        update.commit(self.manifest,staged,prepared)
        update.manage_save_backups(self.manifest,remove=True)
        self.assertEqual((outside/'save').read_text(),'external')

    def test_final_prompt_persists_keep_or_delete_and_does_not_repeat_on_resume(self):
        for choice in ('keep','delete'):
            with self.subTest(choice=choice):
                # Each subcase is a separate completed operation.
                self.setUp(); backups=self.publish()
                script=r'''
source "$WT_ROOT/modules/wsquashfs.sh"
i18n() { shift; printf '%s\n' "$@"; }
msgbox() { :; }
yesno_default_no() { echo prompt >> "$WT_HOME/prompts"; [ "$CHOICE" = delete ]; }
wsq_update_run() { shift 3; "$@"; }
wsq_update_manage_save_backups "$MANIFEST" "$WT_HOME/cleanup.log" || exit 9
wsq_update_manage_save_backups "$MANIFEST" "$WT_HOME/cleanup.log"
'''
                result=subprocess.run(['bash','-c',script],env=dict(os.environ,WT_HOME=str(self.base),WT_ROOT=str(ROOT/'toolbox'),MANIFEST=str(self.manifest),CHOICE=choice),capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual((self.base/'prompts').read_text(),'prompt\n')
                self.assertEqual(backups[0].exists(), choice=='keep')


    def test_keep_is_available_even_after_backup_was_modified(self):
        backups=self.publish(); (backups[0]/'slot').write_text('manual recovery')
        update.manage_save_backups(self.manifest,keep=True)
        self.assertEqual((backups[0]/'slot').read_text(),'manual recovery')
        self.assertEqual(json.loads(self.manifest.read_text())['save_backup_choice'],'keep')

    def test_legacy_single_file_backup_is_removed_without_touching_active_file(self):
        self.prepare(); target=self.saves/'settings.ini'; target.write_text('old')
        prepared=self.saves/'prepared.ini'; prepared.write_text('new')
        data=json.loads(self.manifest.read_text()); data['legacy_publish']=[{'target':str(target),'prepared':str(prepared)}]
        update.save_json(self.manifest,data)
        staged=self.base/'new.wsquashfs';staged.write_bytes(b'new')
        update.commit(self.manifest,staged)
        backups=update.manage_save_backups(self.manifest); self.assertEqual(len(backups),1)
        update.manage_save_backups(self.manifest,remove=True)
        self.assertFalse(backups[0].exists());self.assertEqual(target.read_text(),'new')

    def test_failed_optional_cleanup_keeps_backups_and_does_not_block_completed_update(self):
        backups=self.publish()
        script=r'''
source "$WT_ROOT/modules/wsquashfs.sh"
i18n() { echo "$1"; }
msgbox() { echo warning >> "$WT_HOME/warnings"; }
yesno_default_no() { return 0; }
wsq_update_run() { return 1; }
wsq_update_manage_save_backups "$MANIFEST" "$WT_HOME/cleanup.log"
'''
        result=subprocess.run(['bash','-c',script],env=dict(os.environ,WT_HOME=str(self.base),WT_ROOT=str(ROOT/'toolbox'),MANIFEST=str(self.manifest)),capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(backups[0].exists()); self.assertTrue((self.base/'warnings').exists())
        self.assertEqual(json.loads(self.manifest.read_text())['save_backup_choice'],'keep')


if __name__=='__main__':
    unittest.main()
