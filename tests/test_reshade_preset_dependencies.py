from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import reshade_manager as m
import reshade_presets as p
import reshade_pack as pack
import reshade_preset_dependencies as d
import test_reshade as fixture
import test_reshade_pack as pack_fixture


class PresetDependencyTests(unittest.TestCase):
    setUp = fixture.ReShadeTests.setUp

    def source(self, text='Techniques=CAS@CAS.fx\n'):
        source = self.base / 'new preset.ini'; source.write_text(text)
        return source

    def download(self, job, files=None):
        target = job / 'cache/game-shaders/preset/Merged'
        (target / 'Shaders').mkdir(parents=True)
        for name, data in (files or {'Shaders/CAS.fx': 'technique CAS {}'}).items():
            path = target / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(data)

    def test_check_uses_real_files_and_only_enabled_effects(self):
        source = self.source('Techniques=CAS@CAS.fx\nTechniqueSorting=Other@Private.fx\n[Another.fx]\nValue=3\n')
        result = d.analyze(self.home, self.rom, source)
        self.assertEqual(result['missing'], ['CAS.fx'])
        self.assertEqual(result['packs'], ['sweetfx-shaders'])
        self.assertEqual(result['unknown'], [])
        (self.shaders / 'Merged/Shaders/cas.FX').write_text('custom CAS')
        self.assertEqual(d.analyze(self.home, self.rom, source)['missing'], [])

    def test_private_effect_present_and_bare_technique_need_no_download(self):
        (self.shaders / 'Merged/Shaders/My.fx').write_text('technique CustomAlias {}')
        result = d.analyze(self.home, self.rom, self.source('Techniques=X@My.fx,CustomAlias\n'))
        self.assertEqual(result['missing'], [])
        self.assertEqual(result['unknown'], [])
        result = d.analyze(self.home, self.rom, self.source('Techniques=X@NotPublic.fx,NoSuchAlias\n'))
        self.assertEqual(set(result['unknown']), {'NotPublic.fx', 'NoSuchAlias'})
        self.assertEqual(result['packs'], [])

    def test_ambiguous_source_requires_explicit_choice(self):
        index = self.base / 'index.json'
        index.write_text(json.dumps({'packs': {'one': ['Shared.fx'], 'two': ['Shared.fx']}}))
        result = d.analyze(self.home, self.rom, self.source('Techniques=X@Shared.fx\n'), index=index)
        self.assertEqual(result['ambiguous'], {'Shared.fx': ['one', 'two']})
        self.assertEqual(result['packs'], [])

    def test_commit_keeps_runtime_version_presets_and_existing_shader_bytes(self):
        source = self.source()
        base_shader = self.shaders / 'Merged/Shaders/Original.fx'
        base_shader.write_text('modified shader')
        preset_before = (self.profile / 'ReShadePreset.ini').read_bytes()
        cfg_before = m.read_json(self.config)
        report = d.analyze(self.home, self.rom, source)
        job = d.prepare(self.home, self.rom, source, 'sweetfx-shaders', report['sha256'])
        self.download(job, {'Shaders/CAS.fx': 'technique CAS {}', 'Shaders/Original.fx': 'different upstream copy', 'Textures/noise.png': 'texture'})
        d.finish(self.home, self.rom, job)
        cfg = m.read_json(self.config)
        for key in ('version', 'runtime', 'runtime_hash', 'enabled', 'compiler'):
            self.assertEqual(cfg[key], cfg_before[key])
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_bytes(), preset_before)
        self.assertEqual(base_shader.read_text(), 'modified shader')
        root = Path(cfg['preset_shaders']['root'])
        self.assertEqual((root / 'Shaders/Original.fx').read_text(), 'modified shader')
        self.assertTrue((root / 'Shaders/CAS.fx').is_file())
        self.assertEqual(d.analyze(self.home, self.rom, source)['missing'], [])
        p.import_file(self.home, self.rom, source)
        m.event(self.home, self.rom, 'gameStart')
        self.assertIn('Combined', (self.game / 'ReShade.ini').read_text())

    def test_failed_download_or_changed_config_never_changes_current_preset(self):
        source = self.source()
        result = d.analyze(self.home, self.rom, source)
        job = d.prepare(self.home, self.rom, source, 'sweetfx-shaders', result['sha256'])
        before_cfg = self.config.read_bytes(); before_preset = (self.profile / 'ReShadePreset.ini').read_bytes()
        self.download(job, {'Shaders/Unrelated.fx': 'none'})
        with self.assertRaisesRegex(ValueError, 'still missing'):
            d.finish(self.home, self.rom, job)
        self.assertEqual(self.config.read_bytes(), before_cfg)
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_bytes(), before_preset)
        job = d.prepare(self.home, self.rom, source, 'sweetfx-shaders', result['sha256'])
        self.download(job)
        cfg = m.read_json(self.config); cfg['enabled'] = False; m.save_json(self.config, cfg)
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            d.finish(self.home, self.rom, job)
        self.assertFalse(m.read_json(self.config)['enabled'])

    def test_changed_source_and_active_game_abort_before_commit(self):
        source = self.source(); report = d.analyze(self.home, self.rom, source)
        source.write_text('Techniques=Other@Other.fx\n')
        with self.assertRaisesRegex(ValueError, 'preset changed'):
            d.prepare(self.home, self.rom, source, 'sweetfx-shaders', report['sha256'])
        with patch.object(m, 'ensure_idle', side_effect=ValueError('game active')), self.assertRaisesRegex(ValueError, 'active'):
            d.prepare(self.home, self.rom, source, 'sweetfx-shaders', '0'*64)

    def test_custom_pack_shader_and_addon_survive_extra_shader_install(self):
        self.cfg.update(version='6.3.3', release_id='6.3.3-addons'); m.save_json(self.config, self.cfg)
        archive = pack_fixture.LocalReShadePackTests.bundle(self)
        pack.install(self.home, self.rom, archive, 'Ultra.ini')
        source = self.source()
        report = d.analyze(self.home, self.rom, source)
        job = d.prepare(self.home, self.rom, source, 'sweetfx-shaders', report['sha256'])
        self.download(job, {'Shaders/CAS.fx': 'technique CAS {}', 'Shaders/Glamayre_Fast_Effects.fx': 'standard copy'})
        addon = (self.game / 'citra.addon').read_bytes()
        d.finish(self.home, self.rom, job)
        cfg = m.read_json(self.config)
        self.assertEqual((Path(cfg['preset_shaders']['root']) / 'Shaders/Glamayre_Fast_Effects.fx').read_bytes(), b'custom shader')
        self.assertEqual((self.game / 'citra.addon').read_bytes(), addon)
        self.assertEqual(cfg['release_id'], '6.3.3-addons')

    def test_pack_removal_restores_the_preexisting_standard_shader_view(self):
        source = self.source()
        report = d.analyze(self.home, self.rom, source)
        job = d.prepare(self.home, self.rom, source, 'sweetfx-shaders', report['sha256'])
        self.download(job, {'Shaders/CAS.fx': 'technique CAS {}', 'ReShade.fxh': 'root-level include'})
        d.finish(self.home, self.rom, job)
        cfg = m.read_json(self.config)
        cfg.update(version='6.3.3', release_id='6.3.3-addons')
        m.save_json(self.config, cfg)
        original_view = dict(cfg['preset_shaders'])
        archive = pack_fixture.LocalReShadePackTests.bundle(self)
        pack.install(self.home, self.rom, archive, 'Ultra.ini')
        self.assertNotIn('preset_shaders', m.read_json(self.config))
        pack.remove(self.home, self.rom)
        self.assertEqual(m.read_json(self.config)['preset_shaders'], original_view)
        self.assertEqual(d.analyze(self.home, self.rom, source)['missing'], [])
        self.assertEqual((Path(original_view['root']) / 'ReShade.fxh').read_text(), 'root-level include')



class PresetDependencyUiTests(unittest.TestCase):
    setUp = fixture.ReShadeTests.setUp
    source = PresetDependencyTests.source

    def backend(self):
        backend = self.home / 'reshade/backend/lib'; backend.mkdir(parents=True)
        for name in ('logging', 'ui', 'ui_yad', 'ui_auto', 'utils', 'cli', 'integrity', 'reshade_pins', 'shader_pins', 'config', 'state', 'shader_registry', 'shader_layout', 'shader_build', 'shaders'):
            (backend / (name + '.sh')).write_text('')
        (backend / 'cli.sh').write_text('parseCliArgs() { return 0; }\n')
        (backend / 'config.sh').write_text('init_runtime_config() { return 0; }\n')
        (backend / 'shaders.sh').write_text('ensureSelectedShaderRepos() { [ "${FAIL_DOWNLOAD:-0}" = 0 ]; }\n')
        (backend / 'shader_build.sh').write_text('buildGameShaderDir() { mkdir -p "$MAIN_PATH/game-shaders/$1/Merged/Shaders"; printf "technique CAS {}\\n" > "$MAIN_PATH/game-shaders/$1/Merged/Shaders/CAS.fx"; }\n')
        (backend / 'install.sh').write_text('touch "$WT_HOME/UNEXPECTED_RUNTIME_INSTALL"\n')

    def run_import(self, source, consent='0', fail=False, mode='preset'):
        root = Path(__file__).resolve().parents[1]
        return subprocess.run(['bash', '-c', r'''
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/reshade.sh"
i18n() { printf '%s' "$1"; }
msgbox() { printf '%s\n' "$2" >> "$WT_HOME/messages"; }
yesno_default_no() { printf '%s\n' "$2" >> "$WT_HOME/confirmations"; return "$CONSENT"; }
resh_backend_ready() { return 0; }
resh_prepare_tools() { mkdir -p "$WT_HOME/reshade/bin"; }
if [ "$MODE" = pack ]; then resh_pack_complete_shaders "$ROM"; else resh_import_ini "$ROM" "$SOURCE"; fi
'''], env=dict(os.environ, WT_ROOT=str(root / 'toolbox'), WT_HOME=str(self.home), WT_LANGUAGE='fr',
              WT_LOG_DIR=str(self.base / 'logs'), ROM=str(self.rom), SOURCE=str(source), CONSENT=consent,
              FAIL_DOWNLOAD='1' if fail else '0', MODE=mode), text=True, capture_output=True, timeout=15)

    def installed_pack_with_extra_variant(self, technique='CAS@CAS.fx'):
        self.cfg.update(version='6.3.3', release_id='6.3.3-addons', variant='standard-addons')
        m.save_json(self.config, self.cfg)
        archive = pack_fixture.LocalReShadePackTests.bundle(self, {'Inactive variant.ini': ('Techniques=' + technique + '\n[CAS.fx]\nAmount=0.42\n').encode()})
        pack.install(self.home, self.rom, archive, 'Ultra.ini')
        return pack.dependency_source(self.home, self.rom)

    def test_fft_from_non_active_pack_variant_is_recognized_installed_and_exportable(self):
        import reshade_extra_shaders as extra
        import reshade_pack_export as exporter
        source = self.installed_pack_with_extra_variant('DoNothing@FastFourierTransform.fx')
        report = d.analyze(self.home, self.rom, source)
        self.assertEqual(report['packs'], ['uwt-insane-dev'])
        self.assertEqual(report['unknown'], [])
        before = (self.profile / 'ReShadePreset.ini').read_bytes()
        active = p.index(self.home, self.rom)['active']
        job = d.prepare(self.home, self.rom, source, 'uwt-insane-dev', report['sha256'])
        shader = b'#include "ReShade.fxh"\ntechnique DoNothing {}'
        catalog = self.base / 'dev-catalog.json'
        entry = dict(json.loads(extra.DEV_CATALOG.read_text())['effects'][0], sha256=hashlib.sha256(shader).hexdigest())
        catalog.write_text(json.dumps({'effects': [entry]}))
        target = job / 'cache/game-shaders/preset/Merged/Shaders'
        target.mkdir(parents=True); (target/'ReShade.fxh').write_text('standard include')
        def download(args, **kwargs):
            Path(args[args.index('-o')+1]).write_bytes(shader)
        with patch.object(extra, 'DEV_CATALOG', catalog), patch.object(extra.subprocess, 'run', side_effect=download):
            d.finish(self.home, self.rom, job)
        self.assertEqual(d.analyze(self.home, self.rom, source)['missing'], [])
        self.assertEqual((self.profile/'ReShadePreset.ini').read_bytes(), before)
        self.assertEqual(p.index(self.home, self.rom)['active'], active)
        root = Path(m.read_json(self.config)['preset_shaders']['root'])
        self.assertEqual((root/'Shaders/Glamayre_Fast_Effects.fx').read_text(), 'custom shader')
        self.assertTrue((root/'Shaders/FastFourierTransform.fx').is_file())
        plan = exporter.plan(self.home, rom=self.rom)
        selected = [k for k,v in plan['names'].items() if v == 'Inactive variant.ini']
        path = exporter.export(self.home, rom=self.rom, selected=selected, addons=['citra.addon'], expected=plan['sha256'],
                               title='Custom variant', game='Game', author='Test', credits='Private validation')
        exported, _ = pack.archive(path)
        self.assertTrue(any(n.endswith('/FastFourierTransform.fx') for n in exported))

    def test_pack_checks_all_variants_and_downloads_without_switching_active_preset(self):
        self.backend()
        source = self.installed_pack_with_extra_variant()
        self.assertIn('CAS@CAS.fx', source.read_text())
        self.assertIn('Citra@Citra.fx', source.read_text())
        active = p.index(self.home, self.rom)['active']
        before = (self.profile / 'ReShadePreset.ini').read_bytes()
        runtime = self.runtime.read_bytes()
        result = self.run_import(source, mode='pack')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(p.index(self.home, self.rom)['active'], active)
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_bytes(), before)
        self.assertEqual(self.runtime.read_bytes(), runtime)
        cfg = m.read_json(self.config)
        self.assertEqual(cfg['release_id'], '6.3.3-addons')
        root = Path(cfg['preset_shaders']['root'])
        self.assertTrue((root / 'Shaders/CAS.fx').is_file())
        self.assertEqual((root / 'Shaders/Glamayre_Fast_Effects.fx').read_text(), 'custom shader')
        self.assertEqual(d.analyze(self.home, self.rom, source)['missing'], [])
        # A new game launch uses the augmented view, and removing the pack restores its predecessor.
        m.event(self.home, self.rom, 'gameStart')
        self.assertIn('Combined', (self.game / 'ReShade.ini').read_text())
        pack.remove(self.home, self.rom)
        self.assertNotIn('preset_shaders', m.read_json(self.config))

    def test_pack_cancel_or_download_failure_keeps_import_and_active_settings_for_retry(self):
        self.backend()
        source = self.installed_pack_with_extra_variant()
        cfg = self.config.read_bytes()
        active = (self.profile / 'ReShadePreset.ini').read_bytes()
        for consent, fail in [('1', False), ('0', True)]:
            result = self.run_import(source, consent=consent, fail=fail, mode='pack')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.config.read_bytes(), cfg)
            self.assertEqual((self.profile / 'ReShadePreset.ini').read_bytes(), active)
            self.assertIn('Le pack reste installé', (self.home / 'messages').read_text())

    def test_pack_unknown_effect_in_non_active_variant_requires_explicit_confirmation(self):
        source = self.installed_pack_with_extra_variant('Private@UnknownPrivate.fx')
        result = self.run_import(source, consent='1', mode='pack')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UnknownPrivate.fx', (self.home / 'confirmations').read_text())
        self.assertTrue(m.read_json(self.config)['pack'])
        self.assertNotIn('preset_shaders', m.read_json(self.config))

    def test_managed_ini_downloads_missing_effect_before_import_without_dll_install(self):
        self.backend()
        runtime = self.runtime.read_bytes()
        result = self.run_import(self.source())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CAS@CAS.fx', (self.profile / 'ReShadePreset.ini').read_text())
        self.assertIn('sweetfx-shaders', (self.home / 'confirmations').read_text())
        self.assertEqual(self.runtime.read_bytes(), runtime)
        self.assertFalse((self.home / 'UNEXPECTED_RUNTIME_INSTALL').exists())
        self.assertTrue(m.read_json(self.config)['preset_shaders'])

    def test_cancelling_or_failed_download_keeps_original_preset_and_config(self):
        self.backend()
        source = self.source()
        before_cfg = self.config.read_bytes(); before_preset = (self.profile / 'ReShadePreset.ini').read_bytes()
        for consent, fail in [('1', False), ('0', True)]:
            result = self.run_import(source, consent, fail)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.config.read_bytes(), before_cfg)
            self.assertEqual((self.profile / 'ReShadePreset.ini').read_bytes(), before_preset)

    def test_unknown_effect_requires_confirmation_and_present_custom_effect_does_not(self):
        source = self.source('Techniques=Custom@Private.fx\n')
        result = self.run_import(source, consent='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ne sont pas reconnus', (self.home / 'confirmations').read_text())
        (self.home / 'confirmations').unlink()
        (self.shaders / 'Merged/Shaders/Private.fx').write_text('technique Custom {}')
        result = self.run_import(source, consent='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / 'confirmations').exists())
