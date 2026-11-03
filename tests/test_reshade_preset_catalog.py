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
