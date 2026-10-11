import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resh', ROOT / 'toolbox/helpers/reshade_manager.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
extract_spec = importlib.util.spec_from_file_location('resh_extract', ROOT / 'toolbox/helpers/reshade_extract.py')
extractor = importlib.util.module_from_spec(extract_spec)
extract_spec.loader.exec_module(extractor)


def pe(arch):
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<H', data, 132, 0x8664 if arch == 64 else 0x14c)
    return bytes(data)


class ReShadeTests(unittest.TestCase):
    def test_export_uses_latest_game_preset_and_requires_overwrite_confirmation(self):
        r.event(self.home, self.rom, 'gameStart')
        (self.game / 'ReShadePreset.ini').write_text('Techniques=CAS@CAS.fx\n')
        target = self.base / 'Export with spaces.ini'
        r.export_preset(self.home, self.rom, target)
        self.assertEqual(target.read_text(), 'Techniques=CAS@CAS.fx\n')
        target.write_text('existing personal preset')
        with self.assertRaisesRegex(ValueError, 'confirm overwrite'):
            r.export_preset(self.home, self.rom, target)
        self.assertEqual(target.read_text(), 'existing personal preset')
        r.export_preset(self.home, self.rom, target, True)
        self.assertEqual(target.read_text(), 'Techniques=CAS@CAS.fx\n')
        target.unlink()
        target.symlink_to(self.profile / 'ReShade.ini')
        with self.assertRaises(ValueError):
            r.export_preset(self.home, self.rom, target, True)

    def test_configured_list_returns_enabled_only_without_scanning_rom_library(self):
        self.assertEqual(r.configured_games(self.home, True), [(str(self.rom), 'enabled')])
        self.cfg['enabled'] = False
        r.save_json(self.config, self.cfg)
        self.assertEqual(r.configured_games(self.home, True), [])
        self.assertEqual(r.configured_games(self.home), [(str(self.rom), 'disabled')])
        r.save_json(self.home / 'reshade/games/missing.json', {'rom': str(self.base / 'gone.wsquashfs'), 'enabled': True})
        self.assertEqual(len(r.configured_games(self.home)), 1)

    def test_extractor_accepts_embedded_zip_and_ignores_other_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'setup.exe'
            archive.write_bytes(pe(64))
            with zipfile.ZipFile(archive, 'a') as z:
                z.writestr('ReShade32.dll', pe(32))
                z.writestr('ReShade64.dll', pe(64))
                z.writestr('../outside', b'ignored')
            previous = Path.cwd()
            try:
                os.chdir(folder)
                extractor.extract(['-y', 'e', str(archive)])
                self.assertEqual(Path('ReShade64.dll').read_bytes(), pe(64))
                self.assertEqual(set(p.name for p in Path(folder).iterdir()),
                                 {'setup.exe', 'ReShade32.dll', 'ReShade64.dll'})
            finally:
                os.chdir(previous)

    def test_extractor_missing_payload_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'setup.exe'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('ReShade32.dll', pe(32))
            previous = Path.cwd()
            try:
                os.chdir(folder)
                with self.assertRaises(KeyError):
                    extractor.extract(['-y', 'e', str(archive)])
                self.assertFalse(Path('ReShade32.dll').exists())
            finally:
                os.chdir(previous)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'Toolbox'
        self.rom = self.base / 'Game with spaces.wine'
        self.game = self.rom / 'drive_c/game/Binaries/Win64'
        self.game.mkdir(parents=True)
        self.exe = 'drive_c/game/Binaries/Win64/Game.exe'
        (self.game / 'Game.exe').write_bytes(pe(64))
        self.original = 'ENV=WINEDLLOVERRIDES="xinput1_3=b" MANGOHUD=1 CUSTOM="a b"\nDIR=drive_c/game\nCMD="Binaries/Win64/Game.exe"\nSAVEDIR=drive_c/Saved\nSAVEFILES=one.sav;two.dat\n'
        (self.rom / 'autorun.cmd').write_text(self.original)
        self.runtime = self.home / 'reshade/runtime/reshade/6.8.0/ReShade64.dll'
        self.runtime.parent.mkdir(parents=True)
        self.runtime.write_bytes(pe(64) + b'ReShade')
        self.compiler = self.home / 'reshade/runtime/d3dcompiler_47.dll.64'
        self.compiler.write_bytes(pe(64) + b'Compiler')
        self.shaders = self.home / 'reshade/runtime/game-shaders/example'
        (self.shaders / 'Merged/Shaders').mkdir(parents=True)
        self.cfg = dict(rom=str(self.rom), exe=self.exe, dll='dxgi', arch=64,
                        version='6.8.0', repos='sweetfx-shaders', enabled=True,
                        runtime=str(self.runtime), compiler=str(self.compiler), shaders=str(self.shaders),
                        runtime_hash=r.fingerprint(self.runtime)['sha256'],
                        compiler_hash=r.fingerprint(self.compiler)['sha256'])
        self.config = self.home / 'reshade/games' / (r.key(self.rom) + '.json')
        r.save_json(self.config, self.cfg)
        self.profile = self.home / 'reshade/profiles' / r.key(self.rom)
        self.profile.mkdir(parents=True)
        (self.profile / 'ReShade.ini').write_text('[GENERAL]\nPerformanceMode=0\n[INPUT]\nKeyOverlay=36,0,0,0\n')
        (self.profile / 'ReShadePreset.ini').write_text('Techniques=\n')

    def test_restore_files_links_and_env_without_modifying_runner(self):
        shared = self.base / 'runner-dxgi.dll'
        shared.write_bytes(b'original DXVK')
        (self.game / 'dxgi.dll').symlink_to(shared)
        compiler_dir = self.rom / 'drive_c/windows/system32'
        compiler_dir.mkdir(parents=True)
        (compiler_dir / 'd3dcompiler_47.dll').symlink_to(self.compiler)
        (self.game / 'ReShade.ini').write_text('original config')
        r.event(self.home, self.rom, 'gameStart')
        self.assertFalse((self.game / 'dxgi.dll').is_symlink())
        self.assertEqual(shared.read_bytes(), b'original DXVK')
        text = (self.rom / 'autorun.cmd').read_text()
        self.assertEqual(text.count('ENV='), 1)
        self.assertIn('MANGOHUD=1 CUSTOM="a b"', text)
        self.assertIn('SAVEFILES=one.sav;two.dat', text)
        # Bash must keep prior user overrides AND inherited Batocera DXVK/NVAPI.
        payload = next(l[4:] for l in text.splitlines() if l.startswith('ENV='))
        result = subprocess.run(['bash', '-c', 'WINEDLLOVERRIDES="nvapi=n"; export WINEDLLOVERRIDES\n'
                                 + payload + ' python3 -c \'import os; print(os.environ["WINEDLLOVERRIDES"])\''],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('xinput1_3=b;dxgi=n,b;d3dcompiler_47=n,b', result.stdout)
        # Original explicit user overrides supersede inherited ones, as before.
        (self.game / 'ReShadePreset.ini').write_text('Techniques=CAS@CAS.fx\n')
        r.event(self.home, self.rom, 'gameStop')
        r.set_enabled(self.home, self.rom, False)
        self.assertTrue((self.game / 'dxgi.dll').is_symlink())
        self.assertEqual((self.game / 'dxgi.dll').resolve(), shared)
        self.assertEqual((self.game / 'ReShade.ini').read_text(), 'original config')
        self.assertEqual((self.rom / 'autorun.cmd').read_text(), self.original)
        self.assertEqual((self.profile / 'ReShadePreset.ini').read_text(), 'Techniques=CAS@CAS.fx\n')
        self.assertFalse((self.game / 'ReShadePreset.ini').exists())

    def test_repeated_start_and_recreated_bottle_use_current_baseline(self):
        (self.game / 'dxgi.dll').write_bytes(b'old custom dll')
        r.event(self.home, self.rom, 'gameStart')
        r.event(self.home, self.rom, 'gameStart')
        # Simulate maintenance replacing the entire prefix with a new archive.
        # Rename preserves the old inode while a new prefix receives a new one.
        self.rom.rename(self.base / 'old.wine')
        self.game.mkdir(parents=True)
        (self.game / 'Game.exe').write_bytes(pe(64))
        (self.rom / 'autorun.cmd').write_text(self.original)
        (self.game / 'dxgi.dll').write_bytes(b'new archive dll')
        r.event(self.home, self.rom, 'gameStart')
        r.set_enabled(self.home, self.rom, False)
        self.assertEqual((self.game / 'dxgi.dll').read_bytes(), b'new archive dll')

    def test_shared_windows_directory_is_refused_and_runtime_tampering_is_refused(self):
        shared = self.base / 'shared/windows'
        shared.mkdir(parents=True)
        (self.rom / 'drive_c/windows').symlink_to(shared, target_is_directory=True)
        with self.assertRaises(ValueError):
            r.event(self.home, self.rom, 'gameStart')
        self.assertEqual(list(shared.iterdir()), [])
        self.assertFalse((self.game / 'dxgi.dll').exists())
        (self.rom / 'drive_c/windows').unlink()
        self.runtime.write_bytes(b'changed dll')
        with self.assertRaises(ValueError):
            r.event(self.home, self.rom, 'gameStart')
        self.assertEqual((self.rom / 'autorun.cmd').read_text(), self.original)

    def test_drift_refuses_overwrite_and_keeps_recovery_backup(self):
        (self.game / 'dxgi.dll').write_bytes(b'original')
        r.event(self.home, self.rom, 'gameStart')
        (self.game / 'dxgi.dll').write_bytes(b'changed by another tool')
        with self.assertRaisesRegex(ValueError, 'changed DLL'):
            r.set_enabled(self.home, self.rom, False)
        self.assertEqual((self.game / 'dxgi.dll').read_bytes(), b'changed by another tool')
        self.assertTrue(list((self.home / 'reshade/installations').rglob('*.json')))

    def test_32_bit_and_pc_runner_change(self):
        pc = self.base / 'Other Game.pc'
        pc.mkdir()
        (pc / 'Game.exe').write_bytes(pe(32))
        (pc / 'autorun.cmd').write_text('CMD="Game.exe"\n')
        bottles = self.base / 'bottles'
        with self.assertRaisesRegex(ValueError, 'once'):
            r.locations(pc, 'RunnerA', bottles)
        a = bottles / 'RunnerA' / (pc.name + '.wine')
        b = bottles / 'RunnerB' / (pc.name + '.wine')
        for p in (a, b):
            p.mkdir(parents=True)
            (p / 'user.reg').write_text('#arch=win64\n')
        cfg = dict(self.cfg, rom=str(pc), exe='Game.exe', dll='d3d9', arch=32)
        runtime32 = self.runtime.with_name('ReShade32.dll')
        compiler32 = self.compiler.with_name('d3dcompiler_47.dll.32')
        runtime32.write_bytes(pe(32) + b'ReShade')
        compiler32.write_bytes(pe(32) + b'Compiler')
        cfg.update(runtime=str(runtime32), compiler=str(compiler32),
                   runtime_hash=r.fingerprint(runtime32)['sha256'],
                   compiler_hash=r.fingerprint(compiler32)['sha256'])
        r.save_json(self.home / 'reshade/games' / (r.key(pc) + '.json'), cfg)
        profile = self.home / 'reshade/profiles' / r.key(pc)
        profile.mkdir()
        for name in ('ReShade.ini', 'ReShadePreset.ini'):
            (profile / name).write_bytes((self.profile / name).read_bytes())
        r.event(self.home, pc, 'gameStart', 'RunnerA', bottles)
        self.assertTrue((a / 'drive_c/windows/syswow64/d3dcompiler_47.dll').exists())
        r.event(self.home, pc, 'gameStart', 'RunnerB', bottles)
        self.assertFalse((a / 'drive_c/windows/syswow64/d3dcompiler_47.dll').exists())
        self.assertTrue((b / 'drive_c/windows/syswow64/d3dcompiler_47.dll').exists())
        b.rename(self.base / 'old-pc-bottle')
        b.mkdir()
        (b / 'user.reg').write_text('#arch=win64\n')
        native = b / 'drive_c/windows/syswow64/d3dcompiler_47.dll'
        native.parent.mkdir(parents=True)
        native.write_bytes(b'new bottle compiler')
        r.event(self.home, pc, 'gameStart', 'RunnerB', bottles)
        r.set_enabled(self.home, pc, False)
        self.assertEqual(native.read_bytes(), b'new bottle compiler')
        self.assertFalse((pc / 'd3d9.dll').exists())

    @unittest.skipUnless(shutil.which('mksquashfs') and shutil.which('unsquashfs'), 'squashfs tools unavailable')
    def test_wsquashfs_upper_injection_does_not_modify_archive(self):
        archive = self.base / 'Game.wsquashfs'
        subprocess.run(['mksquashfs', str(self.rom), str(archive), '-noappend', '-processors', '1'],
                       check=True, stdout=subprocess.DEVNULL)
        before = r.fingerprint(archive)
        cfg = dict(self.cfg, rom=str(archive))
        r.save_json(self.home / 'reshade/games' / (r.key(archive) + '.json'), cfg)
        profile = self.home / 'reshade/profiles' / r.key(archive)
        profile.mkdir()
        for n in ('ReShade.ini', 'ReShadePreset.ini'):
            (profile / n).write_bytes((self.profile / n).read_bytes())
        bottles = self.base / 'bottles'
        r.event(self.home, archive, 'gameStart', 'Vanilla-11.5', bottles)
        upper = bottles / 'Vanilla-11.5' / (archive.name + '.wine')
        self.assertTrue((upper / 'drive_c/game/Binaries/Win64/dxgi.dll').exists())
        self.assertIn('WINEDLLOVERRIDES=', (upper / 'autorun.cmd').read_text())
        self.assertEqual(r.fingerprint(archive), before)
        r.set_enabled(self.home, archive, False)
        self.assertFalse((upper / 'drive_c/game/Binaries/Win64/dxgi.dll').exists())
        self.assertEqual((upper / 'autorun.cmd').read_text(), self.original)
        self.assertEqual(r.fingerprint(archive), before)

    def test_partial_write_failure_rolls_back(self):
        (self.game / 'dxgi.dll').write_bytes(b'original')
        atomic = r.atomic_bytes
        def fail_compiler(path, data):
            if path.name == 'd3dcompiler_47.dll' and path.parent == self.game:
                raise OSError('simulated disk error')
            return atomic(path, data)
        with patch.object(r, 'atomic_bytes', side_effect=fail_compiler):
            with self.assertRaises(OSError):
                r.event(self.home, self.rom, 'gameStart')
        self.assertEqual((self.game / 'dxgi.dll').read_bytes(), b'original')
        self.assertEqual((self.rom / 'autorun.cmd').read_text(), self.original)

    def test_mangohud_and_reshade_mounts_survive_either_hook_order(self):
        import re
        hook = (ROOT / 'toolbox/hooks/mangohud-game-event.sh').read_text()
        block = re.search(r'python3 - "\$file"[^\n]*<<\x27PY\x27\n(.*?)\nPY', hook, re.S)[1]
        mango_root = '/userdata/system/ultimate-wine-toolbox/runtime/mangohud'
        def mango(enabled):
            result = subprocess.run(['python3', '-', str(self.rom / 'autorun.cmd'), str(int(enabled)),
                                     '0', 'libMangoHud_shim.so', mango_root + '/lib64/mangohud:' + mango_root + '/lib32/mangohud',
                                     mango_root, 'default'], input=block, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for mango_first in (False, True):
            (self.rom / 'autorun.cmd').write_text(self.original)
            if mango_first:
                mango(True)
            r.event(self.home, self.rom, 'gameStart')
            if not mango_first:
                mango(True)
            text = (self.rom / 'autorun.cmd').read_text()
            payload = next(l[4:] for l in text.splitlines() if l.startswith('ENV='))
            result = subprocess.run(['bash', '-c', payload + ' python3 -c \'import os; print(os.environ["UMU_BATOCERA_EXTRA_RO"])\''], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(self.home / 'reshade/runtime'), result.stdout)
            self.assertIn(mango_root, result.stdout)
            mango(False)
            self.assertIn(str(self.home / 'reshade/runtime'), (self.rom / 'autorun.cmd').read_text())
            r.set_enabled(self.home, self.rom, False)
            cfg = r.read_json(self.config)
            cfg['enabled'] = True
            r.save_json(self.config, cfg)

    def test_active_prefix_refuses_any_file_mutation(self):
        proc = subprocess.Popen(['python3', '-c', 'import time; time.sleep(30)'],
                                env=dict(os.environ, WINEPREFIX=str(self.rom)))
        try:
            with self.assertRaisesRegex(ValueError, 'active'):
                r.event(self.home, self.rom, 'gameStart')
            self.assertFalse((self.game / 'dxgi.dll').exists())
            self.assertEqual((self.rom / 'autorun.cmd').read_text(), self.original)
        finally:
            proc.terminate()
            proc.wait()

    def test_backend_preparation_records_arch_and_finish_rejects_wrong_payload(self):
        ws = r.prepare(self.home, self.rom, self.exe, 'dxgi', '6.8.0', 'sweetfx-shaders')
        pending = r.read_json(ws / 'pending.json')
        backend_state = self.home / 'reshade/runtime/game-state' / (pending['state_key'] + '.state')
        self.assertIn('arch=64', backend_state.read_text())
        (ws / 'dxgi.dll').symlink_to(self.runtime)
        (ws / 'd3dcompiler_47.dll').symlink_to(self.compiler)
        (ws / 'ReShade_shaders').symlink_to(self.shaders, target_is_directory=True)
        backend_state.write_text(backend_state.read_text().replace('selected_repos=\n', 'selected_repos=sweetfx-shaders\n'))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            r.finish(self.home, self.rom)
        with patch.dict(r.COMPILER_HASH, {64: r.fingerprint(self.compiler)['sha256']}):
            cfg = r.finish(self.home, self.rom)
        self.assertEqual(cfg['arch'], 64)
        self.assertEqual(cfg['runtime'], str(self.runtime))
        self.compiler.write_bytes(pe(32))
        with self.assertRaisesRegex(ValueError, 'architecture'):
            r.finish(self.home, self.rom)
