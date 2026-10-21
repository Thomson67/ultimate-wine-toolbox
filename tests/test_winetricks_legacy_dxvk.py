"""Repair stale DXVK links using private, same-architecture runner DLLs."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import wsquashfs_winetricks as tricks
from winetricks_games import configured_runner


class LegacyDXVKTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prefix = self.root / 'Game.wine'
        self.windows = self.prefix / 'drive_c/windows'
        (self.windows / 'system32').mkdir(parents=True)
        (self.windows / 'syswow64').mkdir()
        (self.prefix / 'system.reg').write_text('WINE REGISTRY Version 2\n#arch=win64\n')
        self.runner = self.root / 'wine-proton'

    def dll(self, name, arch, machine, layout='lib/wine'):
        target = self.runner / layout / arch / name
        target.parent.mkdir(parents=True, exist_ok=True)
        pe = bytearray(128)
        pe[:2] = b'MZ'; pe[60:64] = (64).to_bytes(4, 'little')
        pe[64:68] = b'PE\0\0'; pe[68:70] = machine.to_bytes(2, 'little')
        target.write_bytes(pe)
        return target

    def link(self, name='d3d10core.dll', folder='system32', dxvk='x64'):
        link = self.windows / folder / name
        link.symlink_to(f'/userdata/system/wine/dxvk/{dxvk}/{name}')
        return link

    def test_repairs_both_architectures_without_changing_runner_files(self):
        for name in ('d3d8.dll', 'd3d9.dll', 'd3d10.dll', 'd3d10_1.dll', 'd3d10core.dll', 'd3d11.dll', 'd3d12.dll', 'd3d12core.dll', 'dxgi.dll', 'ddraw.dll'):
            for folder, dxvk, arch, machine in (
                    ('system32', 'x64', 'x86_64-windows', 0x8664),
                    ('syswow64', 'x32', 'i386-windows', 0x14c)):
                link = self.link(name, folder, dxvk)
                source = self.dll(name, arch, machine)
                original = source.read_bytes()
                tricks.prepare(self.prefix, runner_root=self.runner)
                self.assertFalse(link.is_symlink())
                self.assertEqual(link.read_bytes(), original)
                self.assertEqual(source.read_bytes(), original)
                self.assertFalse(os.path.samefile(link, source))

    def test_readonly_preflight_leaves_original_link_for_dotnet_snapshot(self):
        link = self.link()
        self.dll('d3d10core.dll', 'x86_64-windows', 0x8664)
        tricks.prepare(self.prefix, detach=False, runner_root=self.runner)
        self.assertTrue(link.is_symlink())
        self.assertFalse(link.exists())

    def test_wrong_architecture_dll_is_refused_without_changing_any_link(self):
        link = self.link()
        self.dll('d3d10core.dll', 'x86_64-windows', 0x14c)
        with self.assertRaisesRegex(ValueError, 'Missing shared Windows file'):
            tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(link.is_symlink())

    def test_unknown_broken_link_is_refused_even_if_runner_has_same_named_dll(self):
        for name in ('d3d10core.dll', 'dxgi.dll', 'other.dll'):
            with self.subTest(name=name):
                link = self.windows / 'system32' / name
                link.symlink_to('/unrecognized/source/' + name)
                self.dll(name, 'x86_64-windows', 0x8664)
                with self.assertRaises(ValueError):
                    tricks.prepare(self.prefix, runner_root=self.runner)
                self.assertTrue(link.is_symlink())
                link.unlink()

    def test_mismatched_link_architecture_is_refused(self):
        link = self.link(folder='syswow64', dxvk='x64')
        self.dll('d3d10core.dll', 'i386-windows', 0x14c)
        with self.assertRaises(ValueError):
            tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(link.is_symlink())

    def test_source_cannot_escape_selected_runner(self):
        link = self.link()
        source = self.dll('d3d10core.dll', 'x86_64-windows', 0x8664)
        external = self.root / 'external.dll'; source.rename(external)
        source.symlink_to(external)
        with self.assertRaises(ValueError):
            tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(link.is_symlink())

    def test_win32_system32_and_umu_files_layout_are_supported(self):
        (self.prefix / 'system.reg').write_text('WINE REGISTRY Version 2\n#arch=win32\n')
        link = self.link(dxvk='x32')
        self.dll('d3d10core.dll', 'i386-windows', 0x14c, 'files/lib/wine')
        tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertFalse(link.is_symlink())

    def test_runner_resolution_uses_original_archive_name_and_legacy_settings(self):
        conf = self.root / 'batocera.conf'
        conf.write_text('windows.core=lutris\nwindows["Original.wsquashfs"].wine-runner=wine-proton\n')
        with patch.dict(os.environ, UWT_COMPONENT_ROM_NAME='Original.wsquashfs'):
            with patch.object(tricks, 'configured_runner', side_effect=lambda prefix, ignored: configured_runner(prefix, conf)):
                self.assertEqual(tricks.selected_runner_root(self.prefix), Path('/usr/wine/wine-proton'))
        conf.write_text('windows.core=proton\n')
        self.assertEqual(configured_runner(self.prefix, conf), 'proton')

    def test_preflight_validates_all_links_before_applying_repairs(self):
        link = self.link()
        self.dll('d3d10core.dll', 'x86_64-windows', 0x8664)
        (self.windows / 'system32/unknown.dll').symlink_to('/missing/unknown.dll')
        with self.assertRaises(ValueError):
            tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(link.is_symlink())

    def test_install_skips_vcrun_repairs_d3d11_then_runs_corefonts(self):
        link = self.link('d3d11.dll')
        self.dll('d3d11.dll', 'x86_64-windows', 0x8664)
        (self.prefix / 'winetricks.log').write_text('vcrun2022\n')
        launcher = self.root / 'batocera-wine'
        launcher.write_text('''#!/bin/bash
waitWineServer() { :; }
cleanAndExit() { :; }
trick_wine() { shift; printf '%s\\n' "$@" > "$TEST_ARGUMENTS"; }
l_PREFIX="$3"
shift 3
            trick_wine "${l_PREFIX}" "$@"
''')
        arguments = self.root / 'arguments'
        with patch.object(tricks, 'selected_runner_root', return_value=self.runner):
            with patch.dict(os.environ, TEST_ARGUMENTS=str(arguments)):
                self.assertEqual(tricks.install(self.prefix, ['vcrun2022', 'corefonts'], launcher), 0)
        self.assertEqual(arguments.read_text().splitlines(), ['-q', 'corefonts'])
        self.assertFalse(link.is_symlink())

    def test_existing_external_dll_is_kept_instead_of_using_runner_replacement(self):
        shared = self.root / 'existing-dxvk.dll'; shared.write_bytes(b'original working DXVK')
        link = self.windows / 'system32/d3d10core.dll'; link.symlink_to(shared)
        with patch.object(tricks, 'legacy_dxvk_source') as fallback:
            tricks.prepare(self.prefix)
        fallback.assert_not_called()
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_bytes(), b'original working DXVK')

    def test_unknown_dll_in_dxvk_directory_is_not_accepted(self):
        link = self.link('other.dll')
        self.dll('other.dll', 'x86_64-windows', 0x8664)
        with self.assertRaises(ValueError):
            tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(link.is_symlink())

    def test_entire_dxvk_batch_is_repaired_together(self):
        links = []
        for name in ('d3d8.dll', 'd3d9.dll', 'd3d10.dll', 'd3d10_1.dll', 'd3d10core.dll', 'd3d11.dll', 'd3d12.dll', 'd3d12core.dll', 'dxgi.dll', 'ddraw.dll'):
            for folder, dxvk, arch, machine in (
                    ('system32', 'x64', 'x86_64-windows', 0x8664),
                    ('syswow64', 'x32', 'i386-windows', 0x14c)):
                links.append(self.link(name, folder, dxvk))
                self.dll(name, arch, machine)
        tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(all(path.is_file() and not path.is_symlink() for path in links))

    def test_stock_dxvk_path_also_supports_directx12(self):
        for name in ('d3d12.dll', 'd3d12core.dll'):
            link = self.windows / 'system32' / name
            link.symlink_to('/usr/wine/dxvk/x64/' + name)
            self.dll(name, 'x86_64-windows', 0x8664)
        tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertFalse(link.is_symlink())

    def test_nvapi_and_optical_flow_use_matching_runner_components(self):
        for name, folder, dxvk, arch, machine in (
                ('nvapi.dll', 'syswow64', 'x32', 'i386-windows', 0x14c),
                ('nvapi64.dll', 'system32', 'x64', 'x86_64-windows', 0x8664),
                ('nvofapi64.dll', 'system32', 'x64', 'x86_64-windows', 0x8664)):
            with self.subTest(name=name):
                link = self.link(name, folder, dxvk)
                source = self.dll(name, arch, machine, 'files/lib/wine/nvapi')
                original = source.read_bytes()
                tricks.prepare(self.prefix, runner_root=self.runner)
                self.assertFalse(link.is_symlink())
                self.assertEqual(link.read_bytes(), original)
                self.assertFalse(os.path.samefile(link, source))
                self.assertEqual(source.read_bytes(), original)

    def test_nvapi_can_use_valid_stock_bundle_when_runner_has_no_nvapi(self):
        link = self.link('nvapi64.dll')
        stock = self.root / 'stock-dxvk'
        source = self.dll('nvapi64.dll', 'x86_64-windows', 0x8664)
        target = stock / 'x64/nvapi64.dll'
        target.parent.mkdir(parents=True)
        source.rename(target)
        with patch.object(tricks, 'DXVK_ROOTS', (Path('/userdata/system/wine/dxvk'), stock)):
            tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertEqual(link.read_bytes(), target.read_bytes())
        self.assertFalse(os.path.samefile(link, target))

    def test_absent_optional_nvapi_links_do_not_block_winetricks(self):
        links = [self.link('nvapi.dll', 'syswow64', 'x32'),
                 self.link('nvapi64.dll'), self.link('nvofapi64.dll')]
        tricks.prepare(self.prefix, detach=False, runner_root=self.runner)
        self.assertTrue(all(path.is_symlink() for path in links))
        tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(all(not path.is_symlink() and not path.exists() for path in links))

    def test_absent_nvapi_removal_waits_for_complete_preflight(self):
        link = self.link('nvapi64.dll')
        (self.windows / 'system32/unknown.dll').symlink_to('/missing/unknown.dll')
        with self.assertRaises(ValueError):
            tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(link.is_symlink())

    def test_nvapi_wrong_folder_or_unknown_target_remains_refused(self):
        link = self.link('nvapi64.dll', 'syswow64', 'x32')
        with self.assertRaises(ValueError):
            tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(link.is_symlink())
        link.unlink()
        link.symlink_to('/unrecognized/nvapi64.dll')
        with self.assertRaises(ValueError):
            tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertTrue(link.is_symlink())

    def test_nvapi_rejects_wrong_pe_architecture(self):
        link = self.link('nvapi64.dll')
        self.dll('nvapi64.dll', 'x86_64-windows', 0x14c, 'lib/nvapi')
        tricks.prepare(self.prefix, runner_root=self.runner)
        self.assertFalse(link.exists())
        self.assertFalse(link.is_symlink())
