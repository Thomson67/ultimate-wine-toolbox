import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import reshade_manager as m
import reshade_pack as pack
import reshade_pack_export as export
import test_reshade as fixture


class PackExportTests(unittest.TestCase):
    setUp = fixture.ReShadeTests.setUp

    def source(self, updates=None):
        files = {
            'ReShade.ini': b'[GENERAL]\nPresetPath=./My preset.ini\nIntermediateCachePath=C:\\private\\cache\n[INPUT]\nKeyOverlay=99\n',
            'My preset.ini': b'Techniques=Used@Used.fx\nTechniqueSorting=Used@Used.fx,Unused@Unused.fx\n[Used.fx]\nAmount=0.73\n[Unused.fx]\nOld=1\n',
            'Other.ini': b'Techniques=Unused@Unused.fx\n',
            'my.addon64': fixture.pe(64), 'unused.addon64': fixture.pe(64),
            'reshade-shaders/Shaders/Used.fx': b'#include "includes/First.fxh"\nuniform float x < source="pingpong"; >;\ntexture2D LUT < source="lut.png"; >;\ntechnique Used {}',
            'reshade-shaders/Shaders/includes/First.fxh': b'#include "Second.fxh"\n',
            'reshade-shaders/Shaders/includes/Second.fxh': b'#include "First.fxh"\n',
            'reshade-shaders/Shaders/Unused.fx': b'technique Unused {}',
            'reshade-shaders/Textures/lut.png': b'used texture',
            'reshade-shaders/Textures/unused.png': b'unused texture',
            'dxgi.dll': b'never distribute the runtime',
        }
        files.update(updates or {})
        source = self.base / 'custom.zip'
        with zipfile.ZipFile(source, 'w') as z:
            for name, data in files.items():
                z.writestr(name, data)
        return source

    def prepare(self, source, **options):
        plan = export.plan(self.home, local=source)
        args = dict(local=source, expected=plan['sha256'], selected=['My preset.ini'], addons=['my.addon64'],
                    game='My game', title='My customization', author='Player', credits='My own shader; add-on MIT, author Example')
        args.update(options)
        return export.export(self.home, **args)

    def test_only_active_effect_recursive_includes_texture_and_selected_addon_round_trip(self):
        path = self.prepare(self.source())
        files, meta = pack.archive(path)
        self.assertEqual(set(files), {'ReShade.ini', 'My preset.ini', 'my.addon64',
                         'reshade-shaders/Shaders/Used.fx', 'reshade-shaders/Shaders/includes/First.fxh',
                         'reshade-shaders/Shaders/includes/Second.fxh', 'reshade-shaders/Textures/lut.png'})
        self.assertIn(b'Amount=0.73', files['My preset.ini'])
        self.assertNotIn(b'private', files['ReShade.ini'])
        self.assertNotIn(b'KeyOverlay', files['ReShade.ini'])
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read('uwt-pack.json'))
            self.assertEqual(manifest['author'], 'Player')
            self.assertEqual(set(manifest['files']), set(files))
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), digest)
        self.assertEqual(path.with_suffix('.zip.sha256').read_text().split()[0], hashlib.sha256(path.read_bytes()).hexdigest())
        self.cfg.update(release_id='6.3.3-addons', arch=64)
        m.save_json(self.config, self.cfg)
        pack.install(self.home, self.rom, path, meta['preferred'])
        self.assertTrue((self.profile / 'pack/assets/my.addon64').is_file())
        self.assertIn('Amount=0.73', (self.profile / 'ReShadePreset.ini').read_text())
        pack.remove(self.home, self.rom)

    def test_selected_citra_addon_preserves_required_adapter_pass(self):
        source = self.source({'citra.addon': fixture.pe(64),
                              'reshade-shaders/Shaders/Citra.fx': b'technique Citra {}'})
        path = self.prepare(source, addons=['citra.addon'])
        files, meta = pack.archive(path)
        self.assertEqual(meta['required_release'], '6.3.3-addons')
        self.assertIn(b'Citra@Citra.fx', files['My preset.ini'])
        self.assertNotIn('my.addon64', files)
        self.assertIn('reshade-shaders/Shaders/Citra.fx', files)

    def test_unrelated_incomplete_preset_is_reported_but_does_not_block_valid_export(self):
        source = self.source({'ReShadePreset.ini': b'Techniques=DoNothing@FastFourierTransform.fx\n'})
        plan = export.plan(self.home, local=source)
        self.assertEqual(plan['default'], 'My preset.ini')
        self.assertNotIn('My preset.ini', plan['issues'])
        self.assertIn('FastFourierTransform.fx', plan['issues']['ReShadePreset.ini'])
        path = self.prepare(source)
        self.assertNotIn('ReShadePreset.ini', pack.archive(path)[0])
        with self.assertRaisesRegex(ValueError, r'preset ReShadePreset.ini: missing shader dependency: FastFourierTransform.fx'):
            self.prepare(source, selected=['My preset.ini', 'ReShadePreset.ini'])
        # A broken active/default preset is never preselected instead of a valid one.
        self.source({'ReShade.ini': b'[GENERAL]\nPresetPath=ReShadePreset.ini\n',
                     'ReShadePreset.ini': b'Techniques=DoNothing@FastFourierTransform.fx\n'})
        self.assertEqual(export.plan(self.home, local=source)['default'], 'My preset.ini')

    def test_ambiguous_dependency_lists_candidates_instead_of_claiming_missing(self):
        source = self.source({'My preset.ini': b'Techniques=DoNothing@FastFourierTransform.fx\n',
                             'reshade-shaders/Shaders/A/FastFourierTransform.fx': b'technique DoNothing {}',
                             'reshade-shaders/Shaders/B/FastFourierTransform.fx': b'technique DoNothing { /* different */ }'})
        issue = export.plan(self.home, local=source)['issues']['My preset.ini']
        self.assertIn('ambiguous shader dependency:', issue)
        self.assertIn('Shaders/A/FastFourierTransform.fx', issue)
        self.assertIn('Shaders/B/FastFourierTransform.fx', issue)
        with self.assertRaisesRegex(ValueError, 'ambiguous shader dependency:'):
            self.prepare(source)

    def test_presets_union_and_explicit_no_addons(self):
        path = self.prepare(self.source(), selected=['My preset.ini', 'Other.ini'], addons=[])
        files, meta = pack.archive(path)
        self.assertIn('reshade-shaders/Shaders/Unused.fx', files)
        self.assertNotIn('reshade-shaders/Textures/unused.png', files)
        self.assertEqual(meta['addons'], {})
        self.assertEqual(len(meta['presets']), 2)

    def test_unknown_ambiguous_and_dynamic_dependencies_fail_without_output(self):
        cases = [
            {'reshade-shaders/Shaders/Used.fx': b'#include VARIABLE\ntechnique Used {}'},
            {'reshade-shaders/Shaders/Used.fx': b'texture2D X < source=VARIABLE; >; technique Used {}'},
            {'reshade-shaders/Shaders/Used.fx': b'#include "Missing.fxh"\ntechnique Used {}'},
            {'My preset.ini': b'Techniques=Missing\n'},
            {'My preset.ini': b'Techniques=Used\n', 'reshade-shaders/Shaders/Duplicate.fx': b'technique Used {}'},
        ]
        for updates in cases:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.prepare(self.source(updates))
        self.assertFalse((self.home / 'exports/community/reshade-packs').exists())

    def test_disabled_addons_and_changed_source_are_rejected(self):
        source = self.source({'ReShade.ini': b'[GENERAL]\nPresetPath=My preset.ini\n[ADDON]\nDisabledAddons=my\n'})
        self.assertNotIn('my.addon64', export.plan(self.home, local=source)['addons'])
        with self.assertRaises(ValueError):
            self.prepare(source)
        source = self.source()
        plan = export.plan(self.home, local=source)
        self.source({'My preset.ini': b'Techniques=Unused@Unused.fx\n'})
        with self.assertRaisesRegex(ValueError, 'changed during review'):
            self.prepare(source, expected=plan['sha256'])

    def test_export_does_not_modify_source_and_requires_credits(self):
        source = self.source()
        before = source.read_bytes()
        with self.assertRaises(ValueError):
            self.prepare(source, credits='')
        self.prepare(source)
        self.assertEqual(source.read_bytes(), before)

    def test_managed_game_exports_saved_customizations_and_preset_subset(self):
        import reshade_presets as presets
        shader = self.shaders / 'Merged/Shaders/Used.fx'
        shader.write_text('technique Used {}')
        (shader.parent / 'Unrelated.fx').write_text('technique Unrelated {}')
        (self.profile / 'ReShadePreset.ini').write_text('Techniques=Used@Used.fx\n[Used.fx]\nCustom=7\n')
        plan = export.plan(self.home, rom=self.rom)
        selected = [plan['preferred']]
        path = export.export(self.home, rom=self.rom, selected=selected, expected=plan['sha256'],
                             game='Game', title='Customized', author='Player', credits='Own creation')
        files, meta = pack.archive(path)
        self.assertIn(b'Custom=7', files[meta['preferred']])
        self.assertNotIn('reshade-shaders/Shaders/Unrelated.fx', files)
        self.assertNotIn('Game with spaces.wine', zipfile.ZipFile(path).read('uwt-pack.json').decode())

    def test_runtime_addon_support_and_large_unrelated_shader_are_not_exported(self):
        shader = self.shaders / 'Merged/Shaders/Used.fx'
        shader.write_text('technique Used {}')
        with (shader.parent / 'Huge.fx').open('wb') as stream:
            stream.truncate(pack.FILE_LIMIT + 1)
        (self.profile / 'ReShadePreset.ini').write_text('Techniques=Used@Used.fx\n')
        plan = export.plan(self.home, rom=self.rom)
        path = export.export(self.home, rom=self.rom, selected=[plan['preferred']], expected=plan['sha256'],
                             game='Game', title='Minimal', author='Player', credits='Own creation')
        self.assertNotIn('reshade-shaders/Shaders/Huge.fx', pack.archive(path)[0])

class PackExportUiTests(unittest.TestCase):
    def test_checklists_preserve_spaces_and_never_send_to_text_service(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            args = Path(tmp) / 'args.json'
            plan = {'names': {'My preset.ini': 'My custom preset', 'Other.ini': 'Other'},
                    'addons': {'my addon.addon64': 64, 'unused.addon64': 64}, 'sha256': 'abc',
                    'default': 'My preset.ini', 'issues': {'Other.ini': 'preset Other.ini: missing shader dependency: FastFourierTransform.fx'}}
            script = r'''
source "$ROOT/toolbox/modules/community.sh"
community_txt() { printf '%s' "$1"; }
i18n() { printf '%s' "$1"; }
menu_select() { printf source; }
resh_pack_source() { printf '/userdata/My custom folder'; }
checklist_select() { printf '%s\n' "$@" >> "$CHECKLIST"; printf '1\n'; }
community_report() { :; }
input_text() { printf 'Public value'; }
yesno_default_no() { return 0; }
msgbox() { :; }
community_service_cmd() { echo 'unexpected submission' >&2; return 1; }
community_cmd() {
 case "$1" in
  reshade-pack-plan) printf '%s' "$PLAN" ;;
  reshade-pack-export) python3 -c 'import json,os,sys;open(os.environ["ARGS"],"w").write(json.dumps(sys.argv[1:]))' "$@"; printf '/userdata/export.zip' ;;
  *) return 1 ;;
 esac
}
community_export_reshade_pack Title
'''
            result = subprocess.run(['bash', '-c', script], text=True, capture_output=True,
                                    env=dict(os.environ, ROOT=str(Path(__file__).resolve().parents[1]),
                                             PLAN=json.dumps(plan), ARGS=str(args), CHECKLIST=str(Path(tmp)/'checklist')))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            actual = json.loads(args.read_text())
            self.assertEqual(actual[actual.index('--preset') + 1], 'My preset.ini')
            self.assertEqual(actual[actual.index('--addon') + 1], 'my addon.addon64')
            self.assertNotIn('Other.ini', actual)
            self.assertNotIn('unused.addon64', actual)
            choices = (Path(tmp)/'checklist').read_text()
            self.assertIn('1\nMy custom preset\non', choices)
            self.assertIn('2\nOther — incomplet\noff', choices)
            self.assertIn('1\nmy addon.addon64 (64 bits)\noff', choices)


if __name__ == '__main__':
    unittest.main()
