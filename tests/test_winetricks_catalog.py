"""Dynamic catalogue and mixed selections with already installed components."""
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import winetricks_catalog as catalogue
import wsquashfs_winetricks as tricks

LISTING = '''diagnostic line
===== apps =====
7zip                    7-Zip [downloadable]
3m_library              Library application
===== dlls =====
corefonts               Fonts (cached)
vcrun2022               Visual C++ 2022
===== prefix =====
apps
dlls
===== settings =====
renderer=gl             Use OpenGL
winver=                 Default Windows version
win10                   Windows 10
--force                 Must not become an option
bad;command             Must not become a command
'''


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prefix = self.root / 'Game.wine'
        (self.prefix / 'drive_c/windows').mkdir(parents=True)
        self.cache = self.root / 'cache/catalog.json'

    def test_parser_includes_numbered_verbs_settings_and_categories_without_headers(self):
        entries = catalogue.parse_catalog(LISTING)
        self.assertEqual([item['verb'] for item in entries],
                         ['3m_library', '7zip', 'corefonts', 'vcrun2022', 'renderer=gl', 'win10', 'winver='])
        self.assertEqual(entries[-1]['category'], 'settings')
        self.assertEqual(entries[0]['description'], 'Library application')
        with self.assertRaises(ValueError):
            catalogue.parse_catalog('warning: no components')
        for value in ('prefix=other', 'arch=win32', '--force', 'x;command', 'vcrun$(id)'):
            self.assertFalse(catalogue.valid_verb(value))
        for value in ('7zip', 'renderer=gl', 'winver=', 'vcrun2022'):
            self.assertTrue(catalogue.valid_verb(value))

    def test_listing_uses_private_prefix_and_cache_is_invalidated_on_script_change(self):
        script = self.root / 'winetricks'; script.write_text('script')
        def run(args, env, **kwargs):
            self.assertEqual(args, ['bash', str(script), 'list-all'])
            self.assertNotEqual(env['WINEPREFIX'], str(self.prefix))
            self.assertEqual(env['WINE'], 'false')
            self.assertEqual(env['WINETRICKS_OPT_NO_STATS'], '1')
            self.assertNotIn('WINETRICKS_LIB', env)
            return subprocess.CompletedProcess(args, 0, LISTING, '')
        with patch.dict(os.environ, WINEPREFIX=str(self.prefix), WINETRICKS_LIB='1'):
            with patch.object(catalogue.subprocess, 'run', side_effect=run) as mock:
                first = catalogue.catalogue(script, self.cache)
                self.assertEqual(catalogue.catalogue(script, self.cache), first)
                self.assertEqual(mock.call_count, 1)
                script.write_text('changed script')
                catalogue.catalogue(script, self.cache)
                self.assertEqual(mock.call_count, 2)
        self.assertEqual(list(self.prefix.iterdir()), [self.prefix / 'drive_c'])

    def test_catalogue_failure_does_not_replace_cached_data(self):
        script = self.root / 'winetricks'; script.write_text('script')
        self.cache.parent.mkdir()
        self.cache.write_text('{"old":"cache"}')
        with patch.object(catalogue.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7, '', 'list failed')):
            with self.assertRaisesRegex(ValueError, 'list failed'):
                catalogue.catalogue(script, self.cache)
        self.assertEqual(self.cache.read_text(), '{"old":"cache"}')

    def test_use_installed_script_for_selected_runner_before_download(self):
        system = self.root / 'system'; system.mkdir()
        custom = self.root / 'custom'; custom.mkdir()
        (system / 'winetricks').write_text('system script')
        (custom / 'winetricks').write_text('custom script')
        self.assertEqual(catalogue.script_for(self.root, '__SYSTEM__', system, custom), system / 'winetricks')
        self.assertEqual(catalogue.script_for(self.root, 'GE-Proton-UMU', system, custom), custom / 'winetricks')

    def test_official_generated_list_is_cached_without_executing_a_script(self):
        with patch.object(catalogue.urllib.request, 'urlopen', return_value=io.BytesIO(LISTING.encode())) as download:
            with patch.object(catalogue.subprocess, 'run') as run:
                first = catalogue.official_catalogue(self.root)
                self.assertEqual(catalogue.official_catalogue(self.root), first)
        self.assertEqual(download.call_count, 1)
        run.assert_not_called()

    def test_offline_catalogue_uses_previous_successful_list(self):
        cached = self.root / 'cache/winetricks/catalog.json'
        cached.parent.mkdir(parents=True)
        entries = catalogue.parse_catalog(LISTING)
        cached.write_text(json.dumps(dict(source='official-all', fetched=0, entries=entries)))
        with patch.object(catalogue.urllib.request, 'urlopen', side_effect=OSError('offline')):
            self.assertEqual(catalogue.official_catalogue(self.root), entries)

    def test_missing_online_list_falls_back_to_local_list_all(self):
        with patch.object(sys, 'argv', ['catalogue', '--home', str(self.root)]):
            with patch.object(catalogue, 'official_catalogue', side_effect=OSError('offline')):
                with patch.object(catalogue, 'script_for', return_value=Path('/installed/winetricks')):
                    with patch.object(catalogue, 'catalogue', return_value=catalogue.parse_catalog(LISTING)) as fallback:
                        with patch.object(sys, 'stdout', new=io.StringIO()):
                            self.assertEqual(catalogue.main(), 0)
        fallback.assert_called_once_with(Path('/installed/winetricks'), self.root / 'cache/winetricks/catalog.json')

    def test_installed_components_skipped_but_settings_reapplied(self):
        (self.prefix / 'winetricks.log').write_text('corefonts\nrenderer=gl\nwin10\n')
        self.cache.parent.mkdir()
        self.cache.write_text(json.dumps(dict(entries=catalogue.parse_catalog(LISTING))))
        self.assertEqual(catalogue.pending_components(
            self.prefix, ['corefonts', 'vcrun2022', 'renderer=gl', 'win10', 'vcrun2022'], self.cache),
            ['vcrun2022', 'renderer=gl', 'win10'])

    def test_mixed_selection_runs_remaining_components_and_preserves_real_failure(self):
        (self.prefix / 'winetricks.log').write_text('corefonts\n')
        launcher = self.root / 'batocera-wine'
        launcher.write_text('''#!/bin/bash
waitWineServer() { :; }
cleanAndExit() { :; }
trick_wine() { shift; printf '%s\\n' "$@" > "$TEST_ARGUMENTS"; return 9; }
l_PREFIX="$3"
shift 3
            trick_wine "${l_PREFIX}" "$@"
''')
        arguments = self.root / 'arguments'
        with patch.dict(os.environ, TEST_ARGUMENTS=str(arguments)):
            self.assertEqual(tricks.install(self.prefix, ['corefonts', 'vcrun2022'], launcher), 9)
        self.assertEqual(arguments.read_text().splitlines(), ['-q', 'vcrun2022'])

    def test_all_installed_is_success_without_launching_wine_or_detaching_files(self):
        (self.prefix / 'winetricks.log').write_text('corefonts\nvcrun2022\n')
        with patch.object(tricks, 'prepare') as prepare, patch.object(tricks.subprocess, 'run') as run:
            self.assertEqual(tricks.install(self.prefix, ['corefonts', 'vcrun2022'], self.root / 'missing-launcher'), 0)
        prepare.assert_not_called()
        run.assert_not_called()

    def test_full_catalogue_menu_passes_numbered_components_and_settings_as_arguments(self):
        binary = self.root / 'batocera-wine'
        binary.write_text('#!/bin/bash\nexit 99\n'); binary.chmod(0o755)
        script = r'''
source "$WT_ROOT/modules/wsquashfs.sh"
prefix="$TEST_ROOT/Game.wine"
runner=__SYSTEM__
WSQ_STATE_DIR="$TEST_ROOT/state"
menu_select() { printf catalogue; }
i18n() { printf '%s' "$1"; }
have_dialog() { return 1; }
python3() { printf '7zip\t[apps] 7-Zip\nrenderer=gl\t[settings] OpenGL\n'; }
checklist_select() { printf '%s\n' "$@" > "$TEST_ROOT/checklist"; printf '7zip\nrenderer=gl\n'; }
yesno_default_no() { return 0; }
wsq_display_path() { printf '%s' "$1"; }
wsq_set_runner_config() { :; }
wt_log() { :; }
wsq_update_run() { printf '%s\n' "$@" > "$TEST_ROOT/installer"; }
msgbox() { exit 88; }
wsq_install_extra_winetricks standalone
'''
        result = subprocess.run(['bash', '-uc', script], capture_output=True, text=True,
                                env=dict(os.environ, WT_ROOT=str(ROOT / 'toolbox'), WT_HOME=str(self.root),
                                         TEST_ROOT=str(self.root), PATH=str(self.root) + ':' + os.environ['PATH']))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'installer').read_text().splitlines()[-2:], ['7zip', 'renderer=gl'])
        checklist = (self.root / 'checklist').read_text()
        self.assertIn('7zip\n[apps] 7-Zip\noff\n', checklist)
        self.assertIn('renderer=gl\n[settings] OpenGL\noff\n', checklist)
