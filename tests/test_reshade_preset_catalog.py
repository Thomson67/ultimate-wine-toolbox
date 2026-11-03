from pathlib import Path
import shutil
import sys
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import reshade_manager as m
import reshade_presets as p
import reshade_preset_catalog as catalog
import test_reshade as fixture


class GlobalPresetCatalogTests(unittest.TestCase):
    setUp = fixture.ReShadeTests.setUp

    def populate(self):
        current = p.listing(self.home, self.rom)[0]['id']
        source = self.base / 'Soft colors.ini'
        source.write_text('Techniques=CAS@CAS.fx\n[CAS.fx]\nAmount=7\n')
        active = p.import_file(self.home, self.rom, source)
        return m.key(self.rom), current, active

    def test_global_list_keeps_deleted_game_and_deletes_active_orphan(self):
        identity, before, active = self.populate()
        m.event(self.home, self.rom, 'gameStart')
        shutil.rmtree(self.rom)
        row = catalog.collections(self.home)[0]
        self.assertEqual(row['status'], 'missing')
        self.assertEqual(row['rom'], str(self.rom))
        self.assertEqual(row['count'], 2)
        saved = catalog.remove(self.home, identity, active)
        self.assertTrue(Path(saved).is_file())
        rows = catalog.items(self.home, identity)['items']
        self.assertNotIn(active, {v['id'] for v in rows})
        self.assertIn(before, {v['id'] for v in rows})
        self.assertFalse(m.read_json(self.config)['enabled'])
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_text(), 'Techniques=\n')
        self.assertNotIn(active, p.index(self.home, self.rom)['items'])

    def test_present_game_preserves_active_and_other_game_data(self):
        identity, before, active = self.populate()
        with self.assertRaisesRegex(ValueError, 'active'):
            catalog.remove(self.home, identity, active)
        with self.assertRaisesRegex(ValueError, 'still installed'):
            catalog.forget(self.home, identity)
        catalog.remove(self.home, identity, before)
        self.assertEqual({v['id'] for v in catalog.items(self.home, identity)['items']}, {active})
        self.assertTrue(self.rom.exists())

    def test_uninstalled_game_keeps_named_association_and_supports_actions(self):
        identity, before, active = self.populate()
        self.config.unlink()
        row = catalog.collections(self.home)[0]
        self.assertEqual(row['status'], 'uninstalled')
        self.assertEqual(row['rom'], str(self.rom))
        catalog.rename(self.home, identity, active, 'My favorite')
        clone = catalog.duplicate(self.home, identity, active, 'My variant')
        report = catalog.details(self.home, identity, clone)
        self.assertIn('My variant', report)
        destination = self.base / 'export.ini'
        catalog.export(self.home, identity, clone, destination)
        self.assertIn('Amount=7', destination.read_text())
        destination.write_text('personal file')
        with self.assertRaisesRegex(ValueError, 'confirm overwrite'):
            catalog.export(self.home, identity, clone, destination)
        self.assertEqual(destination.read_text(), 'personal file')
        catalog.export(self.home, identity, clone, destination, True)
        with self.assertRaises(ValueError):
            catalog.export(self.home, identity, clone, self.profile / 'Other.ini')
        saved = catalog.forget(self.home, identity)
        self.assertFalse(self.profile.exists())
        self.assertTrue(self.rom.exists())
        self.assertEqual(catalog.collections(self.home), [])
        with zipfile.ZipFile(saved) as z:
            self.assertTrue(any('presets/' in n for n in z.namelist()))

    def test_legacy_detached_collection_can_be_managed_without_rom(self):
        identity = m.key(self.rom)
        self.config.unlink()
        self.assertEqual(catalog.collections(self.home)[0]['status'], 'unknown')
        values = catalog.items(self.home, identity)
        self.assertFalse(values['rom'])
        active = values['items'][0]['id']
        catalog.rename(self.home, identity, active, 'Recovered')
        clone = catalog.duplicate(self.home, identity, active, 'Copy')
        catalog.remove(self.home, identity, active)
        self.assertEqual([v['name'] for v in catalog.items(self.home, identity)['items']], ['Copy'])
        catalog.remove(self.home, identity, clone)
        self.assertEqual(catalog.collections(self.home)[0]['count'], 0)
        catalog.forget(self.home, identity)
        self.assertEqual(catalog.collections(self.home), [])

    def test_legacy_path_can_be_recovered_from_workspace(self):
        identity = m.key(self.rom)
        self.config.unlink()
        m.save_json(self.home / 'reshade/workspaces' / identity / 'pending.json', {'rom': str(self.rom)})
        self.assertEqual(catalog.collections(self.home)[0]['rom'], str(self.rom))
        catalog.items(self.home, identity)
        (self.home / 'reshade/workspaces' / identity / 'pending.json').unlink()
        self.assertEqual(catalog.collections(self.home)[0]['rom'], str(self.rom))

    def test_active_process_blocks_orphan_cleanup(self):
        identity, before, active = self.populate()
        m.event(self.home, self.rom, 'gameStart')
        shutil.rmtree(self.rom)
        with patch.object(m, 'ensure_idle', side_effect=ValueError('game active')), self.assertRaisesRegex(ValueError, 'active'):
            catalog.forget(self.home, identity)
        self.assertTrue(self.profile.exists())
        self.assertTrue(self.config.exists())

    def test_forget_retired_archive_restores_remaining_bottle_first(self):
        identity, before, active = self.populate()
        root = self.base / 'surviving-bottle.wine'
        root.mkdir(); (root / 'autorun.cmd').write_text(self.original)
        m.install_files(self.home, self.rom, root, root, self.cfg)
        shutil.rmtree(self.rom)
        self.assertTrue((root / Path(self.exe).parent / 'dxgi.dll').exists())
        catalog.forget(self.home, identity)
        self.assertFalse((root / Path(self.exe).parent / 'dxgi.dll').exists())
        self.assertTrue(root.exists())
        self.assertFalse(self.config.exists())
        self.assertFalse(self.profile.exists())


class ClearAllPresetTests(unittest.TestCase):
    setUp = fixture.ReShadeTests.setUp
    populate = GlobalPresetCatalogTests.populate
    def test_clear_active_collection_preserves_runtime_and_backs_up_all_variants(self):
        identity, before, active = self.populate()
        m.event(self.home, self.rom, 'gameStart')
        journal = m.read_json(m.journal_path(self.home, self.rom, self.rom, self.rom))
        old_files = [Path(n) for n in journal['files'] if 'UWT-ReShadePresets' in n]
        old_version = m.read_json(self.config)['release_id'] if 'release_id' in m.read_json(self.config) else m.read_json(self.config)['version']
        dll = (self.game / 'dxgi.dll').read_bytes()
        saved = catalog.clear_all(self.home, identity)
        rows = p.listing(self.home, self.rom)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['active'])
        self.assertNotIn(rows[0]['id'], (before, active))
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_text(), 'Techniques=\n')
        self.assertEqual((self.game / 'dxgi.dll').read_bytes(), dll)
        self.assertTrue(m.read_json(self.config)['enabled'])
        self.assertEqual(m.read_json(self.config).get('release_id', m.read_json(self.config)['version']), old_version)
        self.assertTrue(all(not v.exists() for v in old_files))
        with zipfile.ZipFile(saved) as z:
            self.assertIn('presets/' + before + '.ini', z.namelist())
            self.assertIn('presets/' + active + '.ini', z.namelist())
            self.assertIn(b'Amount=7', z.read('presets/' + active + '.ini'))

    def test_clear_disabled_collection_stays_disabled(self):
        identity, _, _ = self.populate()
        m.set_enabled(self.home, self.rom, False)
        catalog.clear_all(self.home, identity)
        self.assertFalse(m.read_json(self.config)['enabled'])
        self.assertFalse((self.game / 'dxgi.dll').exists())
        self.assertEqual(len(p.listing(self.home, self.rom)), 1)

    def test_clear_does_not_restore_deleted_presets_when_pack_is_later_removed(self):
        import test_reshade_pack as fixture_pack
        import reshade_pack as pack
        self.cfg.update(version='6.3.3', release_id='6.3.3-addons')
        m.save_json(self.config, self.cfg)
        identity, _, _ = self.populate()
        archive = fixture_pack.LocalReShadePackTests.bundle(self)
        pack.install(self.home, self.rom, archive, 'Ultra.ini')
        old = set(p.index(self.home, self.rom)['items'])
        addon = (self.game / 'citra.addon').read_bytes()
        catalog.clear_all(self.home, identity)
        self.assertEqual((self.game / 'citra.addon').read_bytes(), addon)
        self.assertTrue(m.read_json(self.config)['pack'])
        self.assertEqual((self.profile / 'pack/before/ReShadePreset.ini').read_text(), 'Techniques=\n')
        pack.remove(self.home, self.rom)
        self.assertFalse(old.intersection(p.index(self.home, self.rom)['items']))
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_text(), 'Techniques=\n')

    def test_clear_unknown_orphan_and_keep_association(self):
        identity, _, _ = self.populate()
        self.config.unlink()
        shutil.rmtree(self.rom)
        saved = catalog.clear_all(self.home, identity)
        self.assertTrue(Path(saved).exists())
        self.assertEqual(catalog.items(self.home, identity)['items'], [])
        self.assertEqual(catalog.collections(self.home)[0]['rom'], str(self.rom))

    def test_failed_reenable_restores_old_collection(self):
        identity, _, active = self.populate()
        m.event(self.home, self.rom, 'gameStart')
        before = p.index(self.home, self.rom)
        original = m.event
        calls = 0
        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError('failed to deploy blank preset')
            return original(*args, **kwargs)
        with patch.object(m, 'event', side_effect=fail_once), self.assertRaisesRegex(OSError, 'blank preset'):
            catalog.clear_all(self.home, identity)
        self.assertEqual(p.index(self.home, self.rom)['active'], active)
        self.assertEqual(set(p.index(self.home, self.rom)['items']), set(before['items']))
        self.assertTrue(m.read_json(self.config)['enabled'])
        self.assertIn('Amount=7', (self.game / 'ReShadePreset.ini').read_text())

    def test_clear_is_blocked_while_game_is_running(self):
        identity, _, active = self.populate()
        m.event(self.home, self.rom, 'gameStart')
        with patch.object(m, 'ensure_idle', side_effect=ValueError('game active')), self.assertRaisesRegex(ValueError, 'active'):
            catalog.clear_all(self.home, identity)
        self.assertEqual(p.index(self.home, self.rom)['active'], active)


class GlobalPresetCatalogUiTests(unittest.TestCase):
    def test_main_reshade_menu_exposes_global_manager(self):
        import os
        import subprocess
        import tempfile
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'options'
            result = subprocess.run(['bash', '-c', r'''
source "$WT_ROOT/modules/reshade.sh"
i18n() { echo "$1"; }
community_txt() { echo "$1"; }
msgbox() { return 0; }
menu_select() { printf '%s\n' "$@" > "$OPTIONS"; echo back; }
resh_menu
'''], env=dict(os.environ, WT_ROOT=str(root / 'toolbox'), OPTIONS=str(target)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Gérer les presets installés', target.read_text())

    def test_orphan_details_offer_rename_copy_export_delete_without_activation(self):
        import os
        import subprocess
        import tempfile
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            env = dict(os.environ, WT_ROOT=str(root / 'toolbox'), WT_LANGUAGE='fr', STEP=str(base / 'step'),
                       CALLS=str(base / 'calls'), OPTIONS=str(base / 'options'))
            result = subprocess.run(['bash', '-c', r'''
source "$WT_ROOT/modules/reshade.sh"
i18n() { echo "$1"; }
community_txt() { echo "$1"; }
msgbox() { return 0; }
input_text() { printf 'My renamed preset'; }
resh_preset_file() { printf '/userdata/Export with spaces.ini'; }
yesno_default_no() { return 0; }
resh_cmd() {
 case "$1" in
  presets-global-items) echo '{"rom":"/games/Deleted.wine","orphan":true,"items":[{"id":"bbbbbbbbbbbbbbbbbbbbbbbb","name":"Ultra","active":true}]}';;
  presets-global-info) echo 'Preset details';;
  *) printf '%s\n' "$@" >> "$CALLS";;
 esac
}
menu_select() {
 local step="$(cat "$STEP" 2>/dev/null || echo 0)"
 echo "$((step+1))" > "$STEP"
 printf '%s\n' "$@" >> "$OPTIONS"
 case "$step" in 0) echo bbbbbbbbbbbbbbbbbbbbbbbb;; 1) echo rename;; 2) echo copy;; 3) echo export;; 4) echo delete;; *) echo back;; esac
}
resh_preset_catalog_collection aaaaaaaaaaaaaaaaaaaaaaaa
'''], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            options = (base / 'options').read_text().splitlines()
            self.assertIn('forget', options)
            self.assertNotIn('select', options)
            calls = (base / 'calls').read_text()
            for operation in ('rename', 'copy', 'export', 'delete'):
                self.assertIn('presets-global-' + operation, calls)
            self.assertIn('My renamed preset', calls)
            self.assertIn('/userdata/Export with spaces.ini', calls)

    def test_clear_all_confirmation_and_both_entry_points(self):
        import os
        import subprocess
        import tempfile
        root = Path(__file__).resolve().parents[1]
        for mode in ('game', 'global'):
            for confirm in ('0', '1'):
                with self.subTest(mode=mode, confirm=confirm), tempfile.TemporaryDirectory() as tmp:
                    result_file = Path(tmp) / 'calls'
                    result = subprocess.run(['bash', '-c', r'''
source "$WT_ROOT/modules/reshade.sh"
i18n() { echo "$1"; }
community_txt() { echo "$1"; }
yesno_default_no() { return "$CONFIRM"; }
msgbox() { return 0; }
resh_cmd() { printf '%s\n' "$@" > "$CALLS"; echo /backup/presets.zip; }
resh_clear_all_presets '/games/My game.wine' "$MODE"
'''], env=dict(os.environ, WT_ROOT=str(root / 'toolbox'), CALLS=str(result_file), MODE=mode, CONFIRM=confirm), capture_output=True, text=True)
                    if confirm == '0':
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result_file.read_text().splitlines(),
                                         ['presets-clear' if mode == 'game' else 'presets-global-clear', '/games/My game.wine'])
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(result_file.exists())
