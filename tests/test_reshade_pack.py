import json
from pathlib import Path
import sys
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import reshade_manager as m
import reshade_pack as p
import test_reshade as fixture


class LocalReShadePackTests(unittest.TestCase):
    setUp = fixture.ReShadeTests.setUp

    def bundle(self, overrides=None):
        files = {'ReShade.ini': b'[GENERAL]\nPresetPath=.\\Ultra.ini\nIntermediateCachePath=C:\\Users\\author\\Temp\nPreprocessorDefinitions=RESHADE_DEPTH_INPUT_IS_CITRA=1\n[ADDON]\nDisabledAddons=Generic Depth\n[INPUT]\nKeyOverlay=99\n',
                 'Ultra.ini': b'Techniques=FakeGI@Glamayre_Fast_Effects.fx\nTechniqueSorting=FakeGI@Glamayre_Fast_Effects.fx,Citra@Citra.fx\n[Glamayre_Fast_Effects.fx]\nDOF=1\n',
                 'citra.addon': fixture.pe(64),
                 'reshade-shaders/Shaders/Citra.fx': b'technique Citra {}',
                 'reshade-shaders/Shaders/Glamayre_Fast_Effects.fx': b'custom shader',
                 'reshade-shaders/Textures/noise.png': b'noise'}
        files.update(overrides or {})
        path = self.base / 'A local bundle.zip'
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in files.items():
                z.writestr(name, data)
        return path

    def directory_bundle(self, overrides=None):
        source = self.bundle(overrides)
        target = self.base / 'Extracted bundle with spaces'
        with zipfile.ZipFile(source) as z:
            z.extractall(target)
        return target

    def test_directory_import_keeps_all_presets_and_survives_source_removal(self):
        import shutil
        import reshade_presets as presets
        self.configure()
        directory = self.directory_bundle({'Other.ini': b'Techniques=Citra@Citra.fx\n[Citra.fx]\nScreen=2\n',
                                           'unused.dll': b'never import this'})
        files, metadata = p.archive(directory)
        self.assertNotIn('unused.dll', files)
        self.assertEqual(metadata['presets'], ['Other.ini', 'Ultra.ini'])
        original = (self.profile / 'ReShadePreset.ini').read_bytes()
        result = p.install(self.home, self.rom, directory, metadata['preferred'])
        self.assertEqual(result['archive_sha256'], p.source_digest(directory, files))
        self.assertEqual(len(presets.index(self.home, self.rom)['items']), 3)
        self.assertFalse((self.game / 'unused.dll').exists())
        m.event(self.home, self.rom, 'gameStop')
        m.set_enabled(self.home, self.rom, False)
        shutil.rmtree(directory)
        m.set_enabled(self.home, self.rom, True)
        m.event(self.home, self.rom, 'gameStart')
        self.assertTrue((self.game / 'citra.addon').exists())
        self.assertTrue((self.game / p.STAGE / 'reshade-shaders/Shaders/Citra.fx').exists())
        m.event(self.home, self.rom, 'gameStop')
        p.remove(self.home, self.rom)
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_bytes(), original)

    def test_directory_identity_and_later_preset_addition(self):
        import reshade_presets as presets
        self.configure()
        directory = self.directory_bundle()
        files, metadata = p.archive(directory)
        identity = p.source_digest(directory, files)
        p.install(self.home, self.rom, directory, metadata['preferred'])
        metadata['archive_sha256'] = identity
        self.assertEqual(presets.pack_presets(self.home, self.rom, files, metadata), 1)
        (directory / 'Ultra.ini').write_bytes(files['Ultra.ini'])
        self.assertEqual(p.source_digest(directory, p.archive(directory)[0]), identity)
        (directory / 'Ultra.ini').write_text('Techniques=Citra@Citra.fx\n')
        self.assertNotEqual(p.source_digest(directory, p.archive(directory)[0]), identity)

    def test_directory_rejects_links_special_files_collisions_and_limits_before_install(self):
        import os
        self.configure()
        directory = self.directory_bundle()
        invalid = directory / 'invalid'
        for kind in ('file-link', 'directory-link', 'fifo', 'case', 'size', 'total-size'):
            with self.subTest(kind=kind):
                if kind == 'file-link': invalid.symlink_to(directory / 'Ultra.ini')
                elif kind == 'directory-link': invalid.symlink_to(directory / 'reshade-shaders', target_is_directory=True)
                elif kind == 'fifo': os.mkfifo(invalid)
                elif kind == 'case': invalid = directory / 'ULTRA.ini'; invalid.write_text('Techniques=')
                else: invalid.write_bytes(b'ignored')
                before = self.config.read_bytes()
                limit = patch.object(p, 'FILE_LIMIT', 1) if kind == 'size' else patch.object(p, 'LIMIT', 1) if kind == 'total-size' else patch.object(p, 'LIMIT', p.LIMIT)
                with limit, self.assertRaises(ValueError):
                    p.install(self.home, self.rom, directory, 'Ultra.ini')
                self.assertEqual(self.config.read_bytes(), before)
                self.assertFalse((self.profile / 'pack').exists())
                invalid.unlink()
                invalid = directory / 'invalid'

    def configure(self):
        self.cfg.update(version='6.3.3', release_id='6.3.3-addons', variant='standard-addons')
        m.save_json(self.config, self.cfg)

    def test_import_launch_edit_disable_enable_remove_restores_originals(self):
        self.configure()
        m.event(self.home, self.rom, 'gameStart')
        # Changes in the live config must be captured before making the backup.
        (self.game / 'ReShade.ini').write_text('[GENERAL]\nPerformanceMode=1\n[INPUT]\nKeyOverlay=36,0,0,0\n[OVERLAY]\nFontSize=22\n')
        (self.game / 'citra.addon').write_bytes(b'previous personal add-on')
        before = (self.game / 'ReShadePreset.ini').read_bytes()
        p.install(self.home, self.rom, self.bundle(), 'Ultra.ini')
        config = (self.game / 'ReShade.ini').read_text()
        self.assertIn('UWT-ReShadePack', config)
        self.assertNotIn('Merged', config)
        self.assertIn('KeyOverlay=36,0,0,0', config)
        self.assertIn('FontSize=22', config)
        self.assertNotIn('author', config)
        self.assertIn('DisabledAddons=Generic Depth', config)
        self.assertIn('PerformanceMode=0', config)
        self.assertTrue((self.game / 'ReShadePreset.ini').read_text().startswith('Techniques=Citra@Citra.fx,FakeGI'))
        self.assertEqual((self.game / 'citra.addon').read_bytes(), fixture.pe(64))
        shader = self.game / p.STAGE / 'reshade-shaders/Shaders/Glamayre_Fast_Effects.fx'
        self.assertEqual(shader.read_bytes(), b'custom shader')
        preset = (self.game / 'ReShadePreset.ini').read_text() + '\n[Citra.fx]\nScreen=3\n'
        active_path = p.ini((self.game / 'ReShade.ini').read_bytes()).get('GENERAL', 'PresetPath')
        (self.game / active_path.replace('\\', '/')).write_text(preset)
        m.event(self.home, self.rom, 'gameStop')
        m.set_enabled(self.home, self.rom, False)
        self.assertEqual((self.game / 'citra.addon').read_bytes(), b'previous personal add-on')
        self.assertFalse(shader.exists())
        m.set_enabled(self.home, self.rom, True)
        m.event(self.home, self.rom, 'gameStart')
        self.assertIn('Screen=3', (self.game / 'ReShadePreset.ini').read_text())
        p.remove(self.home, self.rom)
        self.assertEqual((self.game / 'citra.addon').read_bytes(), b'previous personal add-on')
        self.assertEqual((self.game / 'ReShadePreset.ini').read_bytes(), before)
        self.assertIn('FontSize=22', (self.game / 'ReShade.ini').read_text())
        self.assertNotIn('UWT-ReShadePack', (self.game / 'ReShade.ini').read_text())
        self.assertNotIn('pack', m.read_json(self.config))
        self.assertFalse(shader.exists())

    def test_exact_runtime_and_architecture_are_checked_before_mutation(self):
        archive = self.bundle()
        for release, arch in [('6.8.0-addons', 64), ('6.3.3', 64), ('6.3.3-addons', 32)]:
            with self.subTest(release=release, arch=arch):
                self.cfg.update(release_id=release, arch=arch)
                m.save_json(self.config, self.cfg)
                before = self.config.read_bytes()
                with self.assertRaises(ValueError):
                    p.install(self.home, self.rom, archive, 'Ultra.ini')
                self.assertEqual(self.config.read_bytes(), before)
                self.assertFalse((self.profile / 'pack').exists())
                self.assertFalse((self.game / 'citra.addon').exists())

    def test_disabled_import_stays_disabled_and_recreated_game_gets_assets(self):
        self.configure()
        m.set_enabled(self.home, self.rom, False)
        p.install(self.home, self.rom, self.bundle(), 'Ultra.ini')
        self.assertFalse(m.read_json(self.config)['enabled'])
        self.assertFalse((self.game / 'citra.addon').exists())
        m.set_enabled(self.home, self.rom, True)
        m.event(self.home, self.rom, 'gameStart')
        self.assertTrue((self.game / 'citra.addon').exists())
        # Like a recreated temporary bottle, at a new directory/inode.
        self.rom.rename(self.base / 'old.wine')
        self.game.mkdir(parents=True)
        (self.game / 'Game.exe').write_bytes(fixture.pe(64))
        (self.rom / 'autorun.cmd').write_text(self.original)
        m.event(self.home, self.rom, 'gameStart')
        self.assertTrue((self.game / 'citra.addon').exists())
        p.remove(self.home, self.rom)
        self.assertFalse((self.game / 'citra.addon').exists())

    def test_failed_staging_rolls_back_profile_enabled_state_and_game(self):
        self.configure()
        original = (self.profile / 'ReShadePreset.ini').read_bytes()
        # A conflicting directory is detected by the journal preflight.
        (self.game / 'citra.addon').mkdir()
        with self.assertRaises(ValueError):
            p.install(self.home, self.rom, self.bundle(), 'Ultra.ini')
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_bytes(), original)
        self.assertNotIn('pack', m.read_json(self.config))
        self.assertTrue(m.read_json(self.config)['enabled'])
        self.assertFalse((self.profile / 'pack').exists())
        self.assertTrue((self.game / 'dxgi.dll').is_file())

    def test_changed_assets_and_external_addon_changes_are_not_silently_overwritten(self):
        self.configure()
        p.install(self.home, self.rom, self.bundle(), 'Ultra.ini')
        (self.game / 'citra.addon').write_bytes(b'external replacement')
        with self.assertRaisesRegex(ValueError, 'changed DLL'):
            m.set_enabled(self.home, self.rom, False)
        self.assertEqual((self.game / 'citra.addon').read_bytes(), b'external replacement')
        (self.game / 'citra.addon').write_bytes(fixture.pe(64))
        m.set_enabled(self.home, self.rom, False)
        (self.profile / 'pack/assets/citra.addon').write_bytes(b'tampered cache')
        cfg = m.read_json(self.config)
        with self.assertRaisesRegex(ValueError, 'asset changed'):
            m.install_files(self.home, self.rom, self.rom, self.rom, cfg)
        self.assertFalse((self.game / 'citra.addon').exists())

    def test_zip_traversal_symlinks_case_collisions_and_size_limits(self):
        for name in ('../escape.ini', '/absolute.ini', 'C:/drive.ini', 'bad\\name.ini', 'NUL.ini', 'citra.addon '):
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.archive(self.bundle({name: b'no'}))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            p.archive(self.bundle({'CITRA.ADDON': fixture.pe(64)}))
        zpath = self.bundle()
        with zipfile.ZipFile(zpath, 'a') as z:
            info = zipfile.ZipInfo('link.ini')
            info.external_attr = 0o120777 << 16
            z.writestr(info, '../outside')
        with self.assertRaisesRegex(ValueError, 'links'):
            p.archive(zpath)
        with patch.object(p, 'LIMIT', 10), self.assertRaisesRegex(ValueError, 'size limit'):
            p.archive(self.bundle())

    def test_runtime_scripts_and_author_config_are_not_imported(self):
        files, meta = p.archive(self.bundle({'dxgi.dll': b'untrusted runtime', 'hack.py': b'print(1)',
                                           'reshade-shaders/Shaders/hack.py': b'print(1)'}))
        self.assertNotIn('dxgi.dll', files)
        self.assertNotIn('hack.py', files)
        self.assertNotIn('reshade-shaders/Shaders/hack.py', files)
        self.assertEqual(meta['preferred'], 'Ultra.ini')

    def test_pc_and_archive_events_use_the_selected_bottle(self):
        import shutil
        for suffix in ('.pc', '.wsquashfs'):
            with self.subTest(suffix=suffix):
                rom = self.base / ('Emulator' + suffix)
                bottles = self.base / 'bottles'
                prefix = bottles / 'test-runner' / (rom.name + '.wine')
                prefix.mkdir(parents=True)
                (prefix / 'user.reg').write_text('#arch=win64\n')
                if suffix == '.pc':
                    shutil.copytree(self.rom, rom)
                    root = rom
                else:
                    rom.write_bytes(b'archive placeholder')
                    root = prefix
                cfg = dict(self.cfg, rom=str(rom), version='6.3.3', release_id='6.3.3-addons')
                m.save_json(self.home / 'reshade/games' / (m.key(rom) + '.json'), cfg)
                shutil.copytree(self.profile, p.profile(self.home, rom))
                def source(relrom, rel):
                    if rel == 'autorun.cmd':
                        return self.original.encode()
                    if rel == 'user.reg':
                        return b'#arch=win64\n'
                    raise ValueError(rel)
                with patch.object(m, 'source_header', return_value=fixture.pe(64)), patch.object(m, 'archive_bytes', side_effect=source):
                    p.install(self.home, rom, self.bundle(), 'Ultra.ini', 'test-runner', bottles)
                    addon = root / Path(self.exe).parent / 'citra.addon'
                    self.assertTrue(addon.is_file())
                    if suffix == '.wsquashfs':
                        shutil.rmtree(prefix)
                        prefix.mkdir()
                        m.event(self.home, rom, 'gameStart', 'test-runner', bottles)
                        self.assertTrue(addon.is_file())
                    p.remove(self.home, rom, 'test-runner', bottles)
                    self.assertFalse(addon.exists())

    def test_reconfigure_requires_pack_removal(self):
        self.configure()
        p.install(self.home, self.rom, self.bundle(), 'Ultra.ini')
        with self.assertRaisesRegex(ValueError, 'remove the local'):
            m.prepare(self.home, self.rom, self.exe, 'dxgi', '6.8.0', 'none')


class LocalReShadePackUiTests(unittest.TestCase):
    def test_installation_offers_bundle_and_imports_before_enable(self):
        import os
        import subprocess
        import tempfile
        root = Path(__file__).resolve().parents[1]
        for mode in ('install', 'cancel', 'incompatible', 'import-fails'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                backend = base / 'backend.sh'
                backend.write_text('#!/bin/bash\nexit 0\n')
                env = dict(os.environ, WT_ROOT=str(root / 'toolbox'), WT_HOME=tmp, WT_LANGUAGE='fr',
                           RESULT=str(base / 'result'), OPTIONS=str(base / 'options'), MODE=mode,
                           BACKEND=str(backend), WT_LOG_DIR=str(base / 'logs'))
                script = r'''
source "$WT_ROOT/modules/reshade.sh"
RESH_BACKEND="$BACKEND"
community_txt() { printf '%s' "$1"; }
i18n() { printf '%s' "$1"; }
resh_api_select() { printf vulkan; }
resh_version_select() { printf 6.3.3-addons; }
resh_backend_ready() { mkdir -p "$WT_HOME/reshade/runtime"; }
resh_prepare_tools() { mkdir -p "$WT_HOME/reshade/bin"; }
menu_select() { printf '%s\n' "$@" > "$OPTIONS"; printf local-pack; }
resh_pack_menu() { [ "$MODE" != cancel ] || return 1; printf '/userdata/My bundle.zip\nUltra.ini'; }
yesno_default_no() { return 0; }
msgbox() { return 0; }
resh_cmd() {
 case "$1" in
  exes) echo Game.exe;;
  details) :;;
  pack-status) echo '{}';;
  pack-check) [ "$MODE" != incompatible ];;
  backend-packs) printf '%s' "$2";;
  status) echo enabled;;
  prepare) printf '%s\n' "$*" >> "$RESULT"; echo "$WT_HOME/workspace";;
  pack-import) printf '%s\n' "$*" >> "$RESULT"; [ "$MODE" != import-fails ];;
  *) printf '%s\n' "$*" >> "$RESULT";;
 esac
}
resh_install_game '/games/An emulator.wine'
'''
                result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True)
                self.assertEqual(result.stderr, '')
                options = (base / 'options').read_text()
                self.assertIn('community\n', options)
                self.assertIn('local-pack\n', options)
                if mode in ('cancel', 'incompatible'):
                    self.assertFalse((base / 'result').exists())
                    self.assertNotEqual(result.returncode, 0)
                else:
                    calls = (base / 'result').read_text().splitlines()
                    self.assertIn('prepare /games/An emulator.wine Game.exe vulkan 6.3.3 none 6.3.3-addons', calls)
                    imported = 'pack-import /games/An emulator.wine /userdata/My bundle.zip Ultra.ini'
                    self.assertIn(imported, calls)
                    enabled = 'enable /games/An emulator.wine'
                    if mode == 'install':
                        self.assertEqual(result.returncode, 0)
                        self.assertLess(calls.index(imported), calls.index(enabled))
                    else:
                        self.assertNotIn(enabled, calls)
                        self.assertNotEqual(result.returncode, 0)

    def test_directory_picker_uses_yad_directory_mode_and_propagates_cancel(self):
        import os
        import subprocess
        import tempfile
        root = Path(__file__).resolve().parents[1]
        for cancel in ('0', '1'):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as tmp:
                args = Path(tmp) / 'picker-args'
                script = r'''
source "$WT_ROOT/modules/reshade.sh"
community_txt() { printf '%s' "$1"; }
i18n() { printf '%s' "$1"; }
menu_select() { printf directory; }
yad() { printf '%s\n' "$@" > "$ARGS"; [ "$CANCEL" = 0 ] || return 1; printf '/userdata/A local bundle'; }
resh_pack_source
'''
                result = subprocess.run(['bash', '-c', script], text=True, capture_output=True,
                                        env=dict(os.environ, WT_ROOT=str(root / 'toolbox'), WT_LANGUAGE='fr',
                                                 ARGS=str(args), CANCEL=cancel))
                self.assertIn('--directory', args.read_text().splitlines())
                self.assertEqual(result.returncode, int(cancel))
                self.assertEqual(result.stdout, '/userdata/A local bundle' if cancel == '0' else '')

    def test_zip_and_directory_import_use_default_without_a_preset_selector(self):
        import os
        import subprocess
        import tempfile
        root = Path(__file__).resolve().parents[1]
        from itertools import product
        for mode, confirm, kind in product(('apply', 'select'), ('0', '1'), ('zip', 'directory')):
            with self.subTest(mode=mode, confirm=confirm, kind=kind), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                env = dict(os.environ, WT_ROOT=str(root / 'toolbox'), WT_HOME=tmp,
                           KIND=kind, WT_LANGUAGE='fr', RESULT=str(base / 'result'), CONFIRM=confirm, MODE=mode, SUMMARY=str(base / 'summary'),
                           META=json.dumps({'required_release': '6.3.3-addons', 'presets': ['Other.ini', 'Ultra.ini'],
                                            'preferred': 'Ultra.ini', 'addons': {'citra.addon': 64}, 'files': 8, 'bytes': 100}))
                script = r'''
source "$WT_ROOT/modules/reshade.sh"
community_txt() { printf '%s' "$1"; }
i18n() { printf '%s' "$1"; }
# Force the text picker in this UI test regardless of host packages.
command() { if [ "${*: -1}" = yad ]; then return 1; else builtin command "$@"; fi; }
input_text() { if [ "$KIND" = zip ]; then printf '/userdata/My bundle.zip'; else printf '/userdata/My bundle'; fi; }
menu_select() { printf '%s' "$KIND"; }
yesno_default_no() { printf '%s' "$2" > "$SUMMARY"; return "$CONFIRM"; }
msgbox() { return 0; }
resh_cmd() {
 case "$1" in
  pack-status) printf '{}';;
  pack-info) printf '%s' "$META";;
  pack-import) printf '%s\n' "$@" > "$RESULT";;
 esac
}
resh_pack_menu '/userdata/roms/windows/An emulator.wine' "$MODE"
'''
                result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True)
                self.assertEqual(result.stderr, '')
                summary = (base / 'summary').read_text()
                self.assertIn('Presets (2): Other.ini, Ultra.ini', summary)
                self.assertIn('Preset initial : Ultra.ini', summary)
                if confirm == '0' and mode == 'apply':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((base / 'result').read_text().splitlines(),
                                     ['pack-import', '/userdata/roms/windows/An emulator.wine', ('/userdata/My bundle.zip' if kind == 'zip' else '/userdata/My bundle'), 'Ultra.ini'])
                else:
                    self.assertFalse((base / 'result').exists())
                    if confirm == '0':
                        self.assertEqual(result.stdout.splitlines(), [('/userdata/My bundle.zip' if kind == 'zip' else '/userdata/My bundle'), 'Ultra.ini'])
                    else:
                        self.assertNotEqual(result.returncode, 0)
