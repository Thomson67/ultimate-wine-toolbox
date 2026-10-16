"""ReShade community menu flows with real local catalogue/export parsing."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import community_profiles as community
import reshade_manager

PRESET = b'Techniques=CAS@CAS.fx\nTechniqueSorting=CAS@CAS.fx\n[CAS.fx]\nSharpness=0.75\n'
OLD = b'Techniques=Old@Old.fx\n[Old.fx]\nValue=1\n'


class ReShadeCommunityUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.home = self.base/'home'; self.home.mkdir()
        self.rom = self.base/'ReShade Game[L].wine'; self.rom.mkdir()
        self.amx_rom = self.base/'AMX_ONLY.wsquashfs'; self.amx_rom.touch()
        directory = self.home/'reshade/games'; directory.mkdir(parents=True)
        (directory/(reshade_manager.key(self.rom)+'.json')).write_text(json.dumps({'rom': str(self.rom), 'enabled': True}))
        config = self.home/'config'; config.mkdir()
        (config/'antimicrox-games.tsv').write_text(f'{self.amx_rom}\t/userdata/amx-only.amgp\n')
        self.preset = self.base/'ReShade Game.ini'; self.preset.write_bytes(PRESET)
        profile = self.home/'reshade/profiles'/reshade_manager.key(self.rom)/'ReShadePreset.ini'; profile.parent.mkdir(parents=True); profile.write_bytes(PRESET)

    def shell(self, code, language='fr'):
        prefix = r'''
set -u
WT_ROOT="$ROOT/toolbox"
source "$ROOT/toolbox/lib/common.sh"
WT_HOME="$TEST_HOME"; WT_LANGUAGE="$TEST_LANGUAGE"
source "$ROOT/toolbox/lang/$TEST_LANGUAGE.sh"
source "$ROOT/toolbox/modules/community.sh"
source "$ROOT/toolbox/modules/reshade.sh"
msgbox() { printf '%s\n' "$@" >> "$WT_HOME/ui"; }
yesno() { printf '%s\n' "$@" >> "$WT_HOME/ui"; return 0; }
community_report() { printf '%s\n' "$@" >> "$WT_HOME/ui"; }
amx_choose_game() { echo AMX-CALLED >> "$WT_HOME/ui"; return 1; }
amx_profile_file() { echo AMX-CALLED >> "$WT_HOME/ui"; return 1; }
amx_profiles_cmd() { echo AMX-CALLED >> "$WT_HOME/ui"; return 1; }
'''
        result = subprocess.run(['bash', '-c', prefix+code], capture_output=True, text=True,
            env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(self.home), TEST_LANGUAGE=language,
                     TEST_ROM=str(self.rom), TEST_INI=str(self.preset)), timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        ui = (self.home/'ui').read_text() if (self.home/'ui').exists() else ''
        self.assertNotIn('AMX-CALLED', ui)
        return ui

    def test_configured_game_list_uses_reshade_config_and_omits_amx_only_games(self):
        self.assertEqual(community.reshade_games(self.home), [(str(self.rom), 'ReShade Game', 'enabled')])
        (self.home/'reshade/games'/(reshade_manager.key(self.rom)+'.json')).write_text(json.dumps({'rom': str(self.rom), 'enabled': False}))
        self.assertEqual(community.reshade_games(self.home)[0][2], 'disabled')

    def test_main_reshade_menu_shares_game_preset_with_only_reshade_prompts_in_both_languages(self):
        script = r'''
menu_select() {
 printf '%s\n' "$@" >> "$WT_HOME/ui"
 case "$3" in
  all) if [ -f "$WT_HOME/main-once" ]; then echo back; else touch "$WT_HOME/main-once"; echo community; fi;;
  browse) if [ -f "$WT_HOME/community-once" ]; then echo back; else touch "$WT_HOME/community-once"; echo share; fi;;
  game) echo game;;
  scan) echo 1;;
  *) return 1;;
 esac
}
input_text() {
 printf '%s\n' "$2" >> "$WT_HOME/questions"
 printf '%s\n' "$@" >> "$WT_HOME/ui"
 case "$2" in
  'Votre pseudo public'|'Your public nickname') echo Tester;;
  'Packs de shaders'*|'Required shader'*) echo 'Standard: CAS.fx';;
  *) printf '%s' "$3";;
 esac
}
resh_cmd() { [ "$1" = export ] || return 1; [ "$2" = "$TEST_ROM" ] || return 1; cp "$TEST_INI" "$3"; printf '%s' "$3" > "$WT_HOME/exported-temporary"; }
community_service_cmd() {
 [ "$1" = submit ] && [ "$3" = --kind ] && [ "$4" = reshade ] || return 1
 python3 - "$ROOT" "$2" "$WT_HOME/payload.json" <<'PYCODE'
import json,sys
sys.path.insert(0,sys.argv[1]+'/toolbox/helpers')
from community_service import package_data
value=package_data(sys.argv[2])
assert value['metadata']['kind']=='reshade'
open(sys.argv[3],'w').write(json.dumps(value))
print(value['metadata']['id']);print('pending')
PYCODE
}
resh_menu
'''
        for language in ('fr', 'en'):
            with self.subTest(language=language):
                for marker in ('main-once', 'community-once', 'ui', 'questions'): (self.home/marker).unlink(missing_ok=True)
                ui = self.shell(script, language)
                self.assertNotIn('AntiMicroX', ui); self.assertNotIn('Hotkey', ui); self.assertNotIn('AMX_ONLY', ui)
                self.assertEqual(len((self.home/'questions').read_text().splitlines()), 3)
                payload = json.loads((self.home/'payload.json').read_text())
                self.assertEqual(payload['metadata']['game'], 'ReShade Game')
                self.assertEqual(payload['metadata']['requirements'], [])
                self.assertEqual(payload['metadata']['tested_on'], '')
                self.assertEqual(payload['metadata']['notes'], '')
                self.assertNotIn('Versions testées', ui)
                self.assertNotIn('Remarques de compatibilité', ui)
                self.assertEqual(payload['profile'].encode(), PRESET)
                self.assertTrue(list((self.home/'exports/community/reshade').glob('*.zip')))
                self.assertEqual(self.preset.read_bytes(), PRESET)

    def test_manual_ini_sharing_uses_reshade_file_chooser_and_game_metadata(self):
        ui = self.shell(r'''
menu_select() { printf '%s\n' "$@" >> "$WT_HOME/ui"; echo file; }
resh_preset_file() { [ "$1" = import ] || return 1; printf '%s' "$TEST_INI"; }
community_share_game() { [ "$1" = reshade ] || return 1; echo 'Game from ES'; }
input_text() { printf '%s\n' "$@" >> "$WT_HOME/ui"; if [ "$2" = 'Votre pseudo public' ]; then echo Tester; else printf '%s' "$3"; fi; }
resh_cmd() { echo unexpected-export >> "$WT_HOME/ui"; return 1; }
community_send_package() { printf '%s\n' "$@" > "$WT_HOME/sent"; }
community_share reshade 'ReShade — Presets communautaires'
''')
        self.assertNotIn('AntiMicroX', ui); self.assertNotIn('Hotkey', ui); self.assertNotIn('unexpected-export', ui)
        args = (self.home/'sent').read_text().splitlines()
        self.assertEqual(args[2], 'reshade')
        import zipfile
        with zipfile.ZipFile(args[1]) as package: meta = json.loads(package.read('metadata.json'))
        self.assertEqual(meta['kind'], 'reshade'); self.assertEqual(meta['game'], 'Game from ES')

    def test_apply_without_game_context_uses_es_games_and_preserves_previous_preset(self):
        (self.home/'current.ini').write_bytes(OLD)
        ui = self.shell(r'''
menu_select() {
 printf '%s\n' "$@" >> "$WT_HOME/ui"
 if [ "$3" = info ]; then echo apply; else echo 1; fi
}
community_cmd() { [ "$1" = games ] || return 1; printf '%s\tUn jeu de la gamelist ES\n' "$TEST_ROM"; }
resh_cmd() {
 [ "$2" = "$TEST_ROM" ] || return 1
 case "$1" in status) echo enabled;; export) cp "$WT_HOME/current.ini" "$3";; preset) cp "$3" "$WT_HOME/current.ini";; *) return 1;; esac
}
community_import_actions reshade "$TEST_INI" 'ReShade — Presets communautaires'
''')
        self.assertNotIn('AntiMicroX', ui); self.assertNotIn('AMX_ONLY', ui); self.assertNotIn('Hotkey', ui)
        self.assertIn('Un jeu de la gamelist ES', ui)
        self.assertEqual((self.home/'current.ini').read_bytes(), PRESET)
        backups = list((self.home/'exports/community-backups').glob('*.ini'))
        self.assertEqual(len(backups), 1); self.assertEqual(backups[0].read_bytes(), OLD)

    def test_game_without_managed_reshade_runs_wizard_then_applies_download(self):
        for external in ('missing',):
            with self.subTest(external=external):
                for filename in ('ui', 'configured', 'current.ini', 'calls'):
                    (self.home/filename).unlink(missing_ok=True)
                ui = self.shell(r'''
menu_select() { printf '%s\n' "$@" >> "$WT_HOME/ui"; echo apply; }
resh_install_game() { echo wizard >> "$WT_HOME/calls"; touch "$WT_HOME/configured"; printf 'Techniques=Previous\n' > "$WT_HOME/current.ini"; }
resh_cmd() {
 printf '%s\n' "$1" >> "$WT_HOME/calls"
 [ "$2" = "$TEST_ROM" ] || return 1
 case "$1" in
 status) if [ -f "$WT_HOME/configured" ]; then echo enabled; else echo missing; fi;;
 external-info) echo EXTERNAL_STATE;;
 export) cp "$WT_HOME/current.ini" "$3";;
 preset) cp "$3" "$WT_HOME/current.ini";;
 *) return 1;; esac
}
community_import_actions reshade "$TEST_INI" ReShade "$TEST_ROM"
'''.replace('EXTERNAL_STATE', external))
                self.assertEqual((self.home/'current.ini').read_bytes(), PRESET)
                calls = (self.home/'calls').read_text().splitlines()
                self.assertEqual(calls, ['status', 'external-info', 'wizard', 'status', 'export', 'preset'])
                self.assertNotIn('AntiMicroX', ui)
                self.assertIn('ReShade intégré' if external.startswith('external') else 'Installer/configurer ReShade', ui)

    def test_existing_reshade_applies_ini_without_installer_or_managed_import(self):
        ui = self.shell(r'''
menu_select() { echo apply; }
resh_install_game() { echo UNEXPECTED-INSTALL >> "$WT_HOME/ui"; return 1; }
resh_cmd() {
 printf '%s\n' "$1" >> "$WT_HOME/calls"
 case "$1" in
 status) echo missing;; external-info) echo external-enabled;;
 existing-targets) echo drive_c/game;;
 existing-import) [ "$3" = drive_c/game ] && [ "$4" = "$TEST_INI" ] || return 1; echo backup-folder;;
 *) echo UNEXPECTED-MANAGED-IMPORT >> "$WT_HOME/ui"; return 1;; esac
}
community_import_actions reshade "$TEST_INI" ReShade "$TEST_ROM"
''')
        self.assertNotIn('UNEXPECTED', ui)
        self.assertIn('conservant son ReShade existant', ui)
        self.assertEqual((self.home/'calls').read_text().splitlines(),
                         ['status','external-info','existing-targets','existing-import'])

    def test_installation_community_chooser_searches_reshade_and_returns_downloaded_ini(self):
        ui=self.shell(r'''
menu_select() {
 printf '%s\n' "$@" >> "$WT_HOME/ui"
 if [ ! -f "$WT_HOME/searched" ]; then touch "$WT_HOME/searched"; echo search; else echo preset-id; fi
}
input_text() { echo Lighthouse; }
community_cmd() {
 printf '%s\n' "$*" >> "$WT_HOME/calls"
 case "$1" in list) [ "$2" = reshade ] || return 1; printf 'preset-id\tLighthouse — Thomson\n';;
 show) [ "$2" = reshade ] || return 1; printf 'Lighthouse\nRequired packs: SweetFX\n';;
 fetch) [ "$2" = reshade ] || return 1; printf '%s' "$TEST_INI";;
 *) return 1;; esac
}
community_choose_reshade_preset ReShade > "$WT_HOME/chosen"
''')
        self.assertEqual((self.home/'chosen').read_text(),str(self.preset))
        calls=(self.home/'calls').read_text().splitlines()
        self.assertIn('list reshade --query Lighthouse',calls)
        self.assertIn('show reshade preset-id',calls);self.assertIn('fetch reshade preset-id',calls)
        self.assertIn('Required packs: SweetFX',ui);self.assertNotIn('AntiMicroX',ui)

    def test_cancelling_setup_never_imports_or_overwrites_preset(self):
        for outcome in ('decline', 'cancel', 'incomplete'):
            with self.subTest(outcome=outcome):
                for filename in ('ui', 'apply-once', 'wizard'):
                    (self.home/filename).unlink(missing_ok=True)
                ui = self.shell(r'''
menu_select() { if [ -f "$WT_HOME/apply-once" ]; then echo back; else touch "$WT_HOME/apply-once"; echo apply; fi; }
yesno() { [ OUTCOME != decline ]; }
resh_install_game() { touch "$WT_HOME/wizard"; [ OUTCOME = incomplete ]; }
resh_cmd() {
 case "$1" in status|external-info) echo missing;; *) echo UNEXPECTED-WRITE >> "$WT_HOME/ui"; return 1;; esac
}
community_import_actions reshade "$TEST_INI" ReShade "$TEST_ROM"
'''.replace('OUTCOME', outcome))
                self.assertNotIn('UNEXPECTED-WRITE', ui)
                self.assertEqual((self.home/'wizard').exists(), outcome != 'decline')
                self.assertEqual(self.preset.read_bytes(), PRESET)

    def test_disabled_managed_reshade_is_enabled_after_import(self):
        (self.home/'current.ini').write_bytes(OLD)
        ui = self.shell(r'''
menu_select() { echo apply; }
resh_cmd() {
 case "$1" in
 status) echo disabled;;
 export) cp "$WT_HOME/current.ini" "$3";;
 preset) cp "$3" "$WT_HOME/current.ini";;
 enable) touch "$WT_HOME/enabled";;
 *) return 1;; esac
}
community_import_actions reshade "$TEST_INI" ReShade "$TEST_ROM"
''')
        self.assertTrue((self.home/'enabled').exists())
        self.assertEqual((self.home/'current.ini').read_bytes(), PRESET)
        self.assertIn('activer ReShade', ui)

    def test_preset_information_displays_effects_and_settings(self):
        info = community.preset_info(self.preset)
        self.assertIn('Techniques=CAS@CAS.fx', info); self.assertIn('Sharpness=0.75', info)
        self.assertNotIn('Hotkey', info)

    def test_reshade_catalogue_browse_never_shows_antimicrox_entries(self):
        amx = self.base/'amx.amgp'; amx.write_bytes(b'<gamecontroller/>')
        c = community.Community(self.home)
        root = self.base/'catalogue'
        for kind, path, game in [('antimicrox', amx, 'AMX_ONLY'), ('reshade', self.preset, 'ReShade Game')]:
            package, _ = c.share(kind, path, game, game+' title', 'Tester')
            community.approve(package, root)
        catalogue = json.loads((root/'catalog.json').read_text())
        community.atomic(c.cache, community.dump({'source': c.base, 'catalog': catalogue, 'updated': 0}))
        ui = self.shell(r'''
menu_select() {
 printf '%s\n' "$@" >> "$WT_HOME/ui"
 if [ "$3" = browse ]; then
  if [ -f "$WT_HOME/browsed" ]; then echo back; else touch "$WT_HOME/browsed"; echo browse; fi
 else echo "$3"; fi
}
yesno() { return 1; }
community_menu reshade
''')
        self.assertIn('ReShade Game', ui); self.assertNotIn('AMX_ONLY', ui); self.assertNotIn('AntiMicroX', ui)
        with patch.object(community.Community, 'network', return_value=community.dump(catalogue)):
            output = io.StringIO()
            with patch.object(sys, 'argv', ['community', '--home', str(self.home), 'refresh', '--kind', 'reshade']), contextlib.redirect_stdout(output):
                community.main()
        self.assertEqual(output.getvalue().strip(), '1')

    def test_published_removal_requires_confirmation_for_each_tool_and_retains_local_profile(self):
        for kind in ('antimicrox','reshade'):
            for allow in ('yes','no'):
                with self.subTest(kind=kind,confirmed=allow):
                    for filename in ('ui','decided','removed','refreshed','moderation-calls'):(self.home/filename).unlink(missing_ok=True)
                    code=r'''menu_select() {
 printf '%s\n' "$@" >> "$WT_HOME/ui"
 if [ "$3" = pending ]; then
  if [ -f "$WT_HOME/decided" ]; then echo back; else echo published; fi
 elif [ -f "$WT_HOME/decided" ]; then echo back; else echo published-id; fi
}
yesno_default_no() { touch "$WT_HOME/decided"; [ ALLOW = yes ]; }
community_cmd() { [ "$1" = refresh ] && [ "$2" = --kind ] && [ "$3" = KIND ] || return 1; touch "$WT_HOME/refreshed"; }
community_service_cmd() {
 printf '%s\n' "$*" >> "$WT_HOME/moderation-calls"
 case "$1" in
 connect|logout) :;;
 published) [ "$2" = KIND ] || return 1; if [ ! -f "$WT_HOME/removed" ]; then printf 'published-id\tGame — Tester\n'; fi;;
 published-review) [ "$2" = KIND ] && [ "$3" = published-id ] || return 1; printf '%064d\nGame — Tester\n' 0;;
 remove-published) [ "$2" = KIND ] && [ "$3" = published-id ] && [ "$4" = "$(printf '%064d' 0)" ] || return 1; touch "$WT_HOME/removed"; echo removed;;
 *) return 1;; esac
}
community_validate KIND Community
'''.replace('KIND',kind).replace('ALLOW',allow)
                    self.shell(code)
                    self.assertEqual((self.home/'removed').exists(),allow=='yes')
                    self.assertEqual((self.home/'refreshed').exists(),allow=='yes')
                    calls=(self.home/'moderation-calls').read_text().splitlines()
                    self.assertEqual(calls[0],'connect');self.assertEqual(calls[-1],'logout')
                    self.assertEqual(self.preset.read_bytes(),PRESET)

    def test_reshade_validator_sends_reshade_type_for_every_review_action(self):
        ui = self.shell(r'''
menu_select() {
 printf '%s\n' "$@" >> "$WT_HOME/ui"
 case "$3" in pending) if [ -f "$WT_HOME/reviewed" ]; then echo back; else echo pending; fi;; approve) echo approve;; *) echo preset-id;; esac
}
community_service_cmd() {
 printf '%s\n' "$*" >> "$WT_HOME/service-calls"
 case "$1" in
  connect|logout) :;;
  pending) [ "$2" = reshade ] || return 1; if [ ! -f "$WT_HOME/reviewed" ]; then printf 'preset-id\tReShade Game — Preset — Tester\n'; fi;;
  review) [ "$2" = reshade ] || return 1; printf '%064d\nTechniques=CAS@CAS.fx\n' 0;;
  approve) [ "$2" = reshade ] || return 1; touch "$WT_HOME/reviewed"; echo approved;;
  *) return 1;;
 esac
}
community_validate reshade 'ReShade — Presets communautaires'
''')
        self.assertIn('Techniques=CAS@CAS.fx', ui); self.assertNotIn('AntiMicroX', ui)
        calls = (self.home/'service-calls').read_text()
        self.assertIn('pending reshade', calls); self.assertIn('review reshade preset-id', calls); self.assertIn('approve reshade preset-id', calls)


if __name__ == '__main__': unittest.main()
