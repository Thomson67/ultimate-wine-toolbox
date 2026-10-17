"""Back navigation, ranked save lists and preserving existing creation saves."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class WorkflowNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.prefix=self.home/'Game.wine';(self.prefix/'drive_c/game/Saves').mkdir(parents=True)
        (self.prefix/'drive_c/game/Game.exe').write_text('executable')
        self.saves=self.home/'saves';(self.saves/'Game').mkdir(parents=True)
        (self.home/'state').mkdir()
        self.snapshot=self.home/'state/before.json';self.snapshot.write_text('{}')
        self.state=self.home/'state/wsquashfs-builder.json'
        self.state.write_text(json.dumps(dict(prefix=str(self.prefix),snapshot=str(self.snapshot),
            game_name='Game',exe_rel='drive_c/game/Game.exe',runner='__SYSTEM__')))

    def shell(self,code,language='fr'):
        script=r'''
WT_ROOT="$ROOT/toolbox"; WT_HOME="$TEST_HOME"; WT_LANGUAGE="$TEST_LANGUAGE"
source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"; WT_LANGUAGE="$TEST_LANGUAGE"
source "$WT_ROOT/lang/$WT_LANGUAGE.sh"
source "$WT_ROOT/modules/wsquashfs.sh"
WSQ_SAVE_ROOT="$WT_HOME/saves"
msgbox() { :; }
wt_log() { :; }
have_dialog() { return 1; }
'''+code
        result=subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=8,
            env=dict(os.environ,ROOT=str(ROOT),TEST_HOME=str(self.home),TEST_LANGUAGE=language,
                     TEST_PREFIX=str(self.prefix),TEST_SNAPSHOT=str(self.snapshot)))
        self.assertEqual(result.returncode,0,result.stderr)
        return result

    def test_keep_existing_directory_retains_old_and_discards_test_data_without_backup(self):
        source=self.prefix/'drive_c/game/Saves'
        (source/'slot.sav').write_text('tested progression');(source/'.hidden').write_text('hidden')
        (self.saves/'Game/slot.sav').write_text('original progression')
        self.shell(r'''
WSQ_ALLOW_KEEP_EXISTING=1
menu_select() { printf '%s\n' "$@" > "$WT_HOME/options"; echo keep; }
wsq_move_save_data "$TEST_PREFIX" drive_c/game/Saves Game || exit 1
wsq_cleanup_internal_savedir "$TEST_PREFIX" drive_c/game/Saves || exit 2
[ -z "${WSQ_LAST_SAVE_BACKUP:-}" ]
''')
        self.assertEqual((self.saves/'Game/slot.sav').read_text(),'original progression')
        self.assertEqual(list(source.iterdir()),[])
        self.assertFalse((self.home/'backups').exists())
        self.assertIn('keep',(self.home/'options').read_text().splitlines())

    def test_keep_files_and_registry_preserves_destination(self):
        (self.prefix/'drive_c/game/slot.sav').write_text('test slot')
        (self.saves/'Game/slot.sav').write_text('existing slot')
        (self.prefix/'user.reg').write_text('new prefix registry')
        (self.saves/'Game/user.reg').write_text('existing registry')
        self.shell(r'''
WSQ_ALLOW_KEEP_EXISTING=1
menu_select() { echo keep; }
prefix="$TEST_PREFIX"; snapshot="$TEST_SNAPSHOT"; game_name=Game
save_rel=drive_c/game; WSQ_SELECTED_SAVEFILES=slot.sav
wsq_copy_savefiles || exit 1
wsq_copy_registry_save || exit 2
''')
        self.assertEqual((self.saves/'Game/slot.sav').read_text(),'existing slot')
        self.assertEqual((self.saves/'Game/user.reg').read_text(),'existing registry')
        self.assertEqual((self.prefix/'user.reg').read_text(),'new prefix registry')
        self.assertFalse((self.prefix/'drive_c/game/slot.sav').exists())
        self.assertFalse((self.home/'backups').exists())

    def test_keep_missing_individual_file_does_not_discard_test_save(self):
        source=self.prefix/'drive_c/game/slot.sav';source.write_text('only copy')
        self.shell(r'''
WSQ_ALLOW_KEEP_EXISTING=1; menu_select() { echo keep; }
prefix="$TEST_PREFIX"; snapshot="$TEST_SNAPSHOT"; game_name=Game
save_rel=drive_c/game; WSQ_SELECTED_SAVEFILES=slot.sav
wsq_copy_savefiles; [ "$?" -eq 9 ]
''')
        self.assertEqual(source.read_text(),'only copy')
        self.assertEqual(list((self.saves/'Game').iterdir()),[])

    def test_keep_does_not_touch_external_save_link_target(self):
        source=self.prefix/'drive_c/game/Saves';source.rmdir()
        external=self.home/'external';external.mkdir();(external/'slot.sav').write_text('external')
        source.symlink_to(external,target_is_directory=True)
        (self.saves/'Game/slot.sav').write_text('existing')
        self.shell(r'''
WSQ_ALLOW_KEEP_EXISTING=1; menu_select() { echo keep; }
wsq_move_save_data "$TEST_PREFIX" drive_c/game/Saves Game || exit 1
wsq_cleanup_internal_savedir "$TEST_PREFIX" drive_c/game/Saves
''')
        self.assertEqual((external/'slot.sav').read_text(),'external')
        self.assertEqual((self.saves/'Game/slot.sav').read_text(),'existing')
        self.assertTrue(source.is_dir());self.assertFalse(source.is_symlink())

    def test_keep_option_is_not_offered_outside_creation_and_back_changes_nothing(self):
        (self.saves/'Game/slot.sav').write_text('original')
        self.shell(r'''
menu_select() { printf '%s\n' "$@" > "$WT_HOME/options"; return 1; }
wsq_save_destination_prepare "$WSQ_SAVE_ROOT/Game"
[ "$?" -eq 10 ]
''')
        self.assertNotIn('keep',(self.home/'options').read_text().splitlines())
        self.assertEqual((self.saves/'Game/slot.sav').read_text(),'original')

    def test_more_locations_only_has_lower_scores_and_back_returns_to_primary(self):
        scores=[120,115,110,105,100,90,90,50,30]
        (self.home/'candidates').write_text(''.join(f'{score}\t1\tdrive_c/game/p{i}\treason\n' for i,score in enumerate(scores,1)))
        (self.home/'queue').write_text('more\nBACK\nmore\n9\n')
        self.shell(r'''
python3() {
 if [ "$1" = "$WSQ_HELPER" ]; then
  case "$2" in diff) cat "$WT_HOME/candidates";; validate-save) printf '%s' "$4";; *) return 1;; esac
 else command python3 "$@"; fi
}
menu_select() {
 local choice number=0
 [ ! -f "$WT_HOME/count" ] || number="$(cat "$WT_HOME/count")"
 number=$((number+1)); echo "$number" > "$WT_HOME/count"
 printf '%s\n' "$@" > "$WT_HOME/menu.$number"
 IFS= read -r choice < "$WT_HOME/queue"
 tail -n +2 "$WT_HOME/queue" > "$WT_HOME/queue.tmp"; mv "$WT_HOME/queue.tmp" "$WT_HOME/queue"
 [ "$choice" != BACK ] || return 1
 echo "$choice"
}
wsq_review_save_candidate() { WSQ_SELECTED_SAVE="$1"; return 0; }
exe_rel=drive_c/game/Game.exe
wsq_select_save_candidate "$TEST_PREFIX" "$TEST_SNAPSHOT" || exit 1
printf '%s' "$WSQ_SELECTED_SAVE" > "$WT_HOME/selected"
''')
        primary=(self.home/'menu.1').read_text().splitlines()[2::2]
        lower=(self.home/'menu.2').read_text().splitlines()[2::2]
        self.assertIn('7',primary);self.assertNotIn('8',primary);self.assertIn('more',primary)
        self.assertEqual(lower,['8','9','back'])
        self.assertEqual((self.home/'menu.1').read_text(),(self.home/'menu.3').read_text())
        self.assertEqual((self.home/'selected').read_text(),'drive_c/game/p9')

    def test_back_on_save_list_preserves_pending_state(self):
        self.shell(r'''
python3() { [ "$1" != "$WSQ_HELPER" ] || return 0; command python3 "$@"; }
menu_select() { return 1; }
exe_rel=drive_c/game/Game.exe
wsq_select_save_candidate "$TEST_PREFIX" "$TEST_SNAPSHOT"
[ "$?" -eq 12 ]
''')
        self.assertTrue(self.state.exists());self.assertTrue(self.snapshot.exists())

    def test_creation_back_revisits_previous_steps_without_losing_pending_state(self):
        self.shell(r'''
wsq_review_launch() { echo review >> "$WT_HOME/order"; }
wsq_select_save_candidate() {
 echo select >> "$WT_HOME/order"
 if [ ! -f "$WT_HOME/selected-once" ]; then touch "$WT_HOME/selected-once"; return 12; fi
 WSQ_SAVE_KIND=directory; WSQ_SELECTED_SAVE=drive_c/game/Saves
}
yesno_default_no() {
 echo confirm >> "$WT_HOME/order"
 if [ ! -f "$WT_HOME/confirmed-once" ]; then touch "$WT_HOME/confirmed-once"; return 1; fi
 return 0
}
wsq_move_save_data() {
 echo move >> "$WT_HOME/order"
 [ -s "$WSQ_STATE_FILE" ] || exit 7
 if [ ! -f "$WT_HOME/moved-once" ]; then touch "$WT_HOME/moved-once"; return 10; fi
 return 0
}
wsq_cleanup_internal_savedir() { echo cleanup >> "$WT_HOME/order"; }
wsq_write_autorun() { echo autorun >> "$WT_HOME/order"; }
yesno() { return 1; }
wsq_resume_build
[ "$?" -eq 12 ]
''')
        self.assertEqual((self.home/'order').read_text().splitlines(),['review','select','review','select','confirm','select','confirm','move','select','confirm','move','cleanup','autorun'])
        self.assertFalse(self.state.exists())

    def test_update_back_from_save_selection_revisits_game_review(self):
        data=json.loads(self.state.read_text());data.update(mode='update',phase='testing');self.state.write_text(json.dumps(data))
        self.shell(r'''
wsq_review_launch() { echo review >> "$WT_HOME/order"; }
wsq_resume_update() {
 echo saves >> "$WT_HOME/order"
 if [ ! -f "$WT_HOME/once" ]; then touch "$WT_HOME/once"; return 12; fi
 return 0
}
wsq_resume_build
''')
        self.assertEqual((self.home/'order').read_text().splitlines(),['review','saves','review','saves'])
        self.assertTrue(self.state.exists())

    def test_back_label_is_scoped_and_translated_for_wizard_menus(self):
        for language,expected in [('fr','Retour'),('en','Back')]:
            with self.subTest(language=language):
                self.shell(r'''
have_dialog() { return 0; }
dialog() { printf '%s\n' "$@" > "$WT_HOME/dialog-options"; return 1; }
WT_MENU_CANCEL_LABEL="$(i18n back)"
menu_select title body one label
[ "$?" -eq 1 ]
''',language)
                options=(self.home/'dialog-options').read_text().splitlines()
                self.assertEqual(options[options.index('--cancel-label')+1],expected)

    def test_update_source_back_returns_to_archive_list_before_any_preparation(self):
        self.shell(r'''
unsquashfs() { :; }; mksquashfs() { :; }
wsq_pending_guard() { return 0; }
python3() {
 if [ "$1" = "$WSQ_UPDATE_HELPER" ] && [ "$2" = listing ]; then printf '%s/Game.wsquashfs\t0\n' "$WT_HOME";
 else command python3 "$@"; fi
}
menu_select() {
 echo archive >> "$WT_HOME/order"
 if [ -f "$WT_HOME/archive-twice" ]; then return 1; fi
 if [ -f "$WT_HOME/archive-once" ]; then touch "$WT_HOME/archive-twice"; else touch "$WT_HOME/archive-once"; fi
 echo 1
}
wsq_update_select_source() {
 echo source >> "$WT_HOME/order"
 if [ ! -f "$WT_HOME/source-once" ]; then touch "$WT_HOME/source-once"; return 1; fi
 if [ -f "$WT_HOME/source-twice" ]; then return 1; fi
 touch "$WT_HOME/source-twice"; echo "$TEST_PREFIX"
}
maintenance_detect_wsquashfs_type() { echo wine; }
wsq_update_prefix_target() { echo target >> "$WT_HOME/order"; return 1; }
wsq_update_new
:
''')
        self.assertEqual((self.home/'order').read_text().splitlines(),['archive','source','archive','source','target','source','archive'])
        self.assertTrue(self.state.exists())

    def test_runner_back_returns_to_executable_before_launch(self):
        self.shell(r'''
unsquashfs() { :; }
wsq_pending_guard() { return 0; }
wsq_select_source_game() { echo "$TEST_PREFIX"; }
wsq_clean_name() { echo Game; }
wsq_select_executable() { echo executable >> "$WT_HOME/order"; echo drive_c/game/Game.exe; }
wsq_select_runner() {
 echo runner >> "$WT_HOME/order"
 if [ ! -f "$WT_HOME/once" ]; then touch "$WT_HOME/once"; return 1; fi
 echo __SYSTEM__
}
wsq_write_autorun() { echo autorun >> "$WT_HOME/order"; }
wsq_set_runner_config() { echo config >> "$WT_HOME/order"; }
wsq_save_state() { return 0; }
wsq_request_game_launch() { echo launch >> "$WT_HOME/order"; }
wsq_restart_emulationstation_deferred() { return 0; }
wsq_create_new
''')
        self.assertEqual((self.home/'order').read_text().splitlines(),['executable','runner','executable','runner','autorun','config','launch'])
