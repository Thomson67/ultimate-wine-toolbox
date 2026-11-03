import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resh_compat', ROOT / 'toolbox/helpers/reshade_compat.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def make_archive(path, entries):
    with tarfile.open(path, 'w:gz') as tar:
        for name, value in entries:
            item = tarfile.TarInfo(name)
            if value is None:
                item.type = tarfile.SYMTYPE
                item.linkname = '../../outside'
                tar.addfile(item)
            else:
                item.size = len(value)
                tar.addfile(item, io.BytesIO(value))


class ReShadeCompatibilityTests(unittest.TestCase):
    def test_pinned_backend_commands_download_exact_commit_and_protect_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            archive = base / 'fixture.tar.gz'
            destination = base / 'cache'
            commit = 'a' * 40
            make_archive(archive, [('repo/Shaders/Effect.fx', b'branch')])
            def download(args, **kwargs):
                shutil.copyfile(archive, args[-1])
            with patch.object(c.subprocess, 'run', side_effect=download) as fetch:
                c.snapshot('https://github.com/example/shaders', 'HEAD', destination)
                c.git_call(['-C', str(destination), 'rev-parse', 'HEAD'])
                c.git_call(['-C', str(destination), 'for-each-ref', '--contains', 'uwt-snapshot', 'refs/remotes'])
                with self.assertRaises(ValueError):
                    c.git_call(['-C', str(destination), 'cat-file', '-e', commit + '^{commit}'])
                c.git_call(['-C', str(destination), 'fetch', '--depth', '1', 'origin', commit])
                make_archive(archive, [('repo/Shaders/Effect.fx', b'pinned')])
                c.git_call(['-C', str(destination), '-c', 'advice.detachedHead=false',
                            'checkout', '--quiet', '--detach', commit])
                self.assertEqual(fetch.call_args.args[0][-3], 'https://codeload.github.com/example/shaders/tar.gz/' + commit)
                c.git_call(['-C', str(destination), 'cat-file', '-e', commit + '^{commit}'])
                effect = destination / 'Shaders/Effect.fx'
                self.assertEqual(effect.read_bytes(), b'pinned')
                effect.write_bytes(b'user edit')
                with self.assertRaisesRegex(ValueError, 'local shader edits'):
                    c.git_call(['-C', str(destination), 'checkout', '--quiet', '--detach', 'b' * 40])
                self.assertEqual(effect.read_bytes(), b'user edit')

    def test_private_extractor_is_used_even_when_system_7z_is_broken(self):
        with tempfile.TemporaryDirectory(prefix='ReShade spaces ') as folder:
            base = Path(folder)
            broken = base / 'system-bin'
            broken.mkdir()
            sentinel = base / 'system-7z-was-called'
            executable = broken / '7z'
            executable.write_text('#!/bin/bash\ntouch "$SENTINEL"\nexit 77\n')
            executable.chmod(0o755)
            archive = base / 'installer.exe'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('ReShade32.dll', b'MZ32')
                z.writestr('ReShade64.dll', b'MZ64')
            env = dict(os.environ, PATH=str(broken) + ':' + os.environ['PATH'],
                       WT_ROOT=str(ROOT / 'toolbox'), WT_HOME=str(base / 'home'),
                       SENTINEL=str(sentinel), INSTALLER=str(archive))
            result = subprocess.run(['bash', '-c',
                'source "$WT_ROOT/modules/reshade.sh"; resh_prepare_tools || exit; '
                'PATH="$WT_HOME/reshade/bin:$PATH" 7z -y e "$INSTALLER"'],
                cwd=base, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(sentinel.exists())
            self.assertEqual((base / 'ReShade64.dll').read_bytes(), b'MZ64')

    def test_file_adapter_checks_real_pe_header_and_bitness(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'Game.exe'
            for machine, expected in [(0x8664, 'x86-64'), (0x14c, '80386')]:
                data = bytearray(256)
                data[:2] = b'MZ'
                struct.pack_into('<I', data, 0x3c, 128)
                data[128:132] = b'PE\0\0'
                struct.pack_into('<H', data, 132, machine)
                p.write_bytes(data)
                self.assertIn('executable', c.describe(p))
                self.assertIn(expected, c.describe(p))
            p.write_bytes(b'MZ is not enough')
            with self.assertRaises(ValueError):
                c.describe(p)

    def test_shader_snapshot_update_preserves_local_edits_and_failed_download(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            archive = base / 'fixture.tar.gz'
            make_archive(archive, [('repo-branch/Shaders/Effect.fx', b'first')])
            destination = base / 'cache'
            def download(args, **kwargs):
                self.assertEqual(args[-3], 'https://codeload.github.com/example/shaders/tar.gz/slim')
                shutil.copyfile(archive, args[-1])
            with patch.object(c.subprocess, 'run', side_effect=download):
                c.git_call(['-c', 'http.lowSpeedLimit=1000', 'clone', '--depth', '1',
                            '--branch', 'slim', '--single-branch', 'https://github.com/example/shaders', str(destination)])
                effect = destination / 'Shaders/Effect.fx'
                self.assertEqual(effect.read_bytes(), b'first')
                make_archive(archive, [('repo-branch/Shaders/Effect.fx', b'second')])
                c.git_call(['-C', str(destination), 'pull', '--ff-only'])
                self.assertEqual(effect.read_bytes(), b'second')
                effect.write_bytes(b'user edits')
                with self.assertRaisesRegex(ValueError, 'local shader edits'):
                    c.git_call(['-C', str(destination), 'pull', '--ff-only'])
                self.assertEqual(effect.read_bytes(), b'user edits')
                effect.write_bytes(b'second')
                make_archive(archive, [('repo-branch/../outside', b'unsafe')])
                with self.assertRaises(ValueError):
                    c.git_call(['-C', str(destination), 'pull', '--ff-only'])
                self.assertEqual(effect.read_bytes(), b'second')
                self.assertEqual(json.loads((destination / '.git/uwt-archive.json').read_text())['branch'], 'slim')
            with self.assertRaises(ValueError):
                c.snapshot('https://example.com/unapproved', 'main', base / 'other')

    def test_shader_archive_rejects_links_and_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / 'source'
            source.mkdir()
            archive = base / 'fixture.tar.gz'
            for entry in [('repo/../../outside', b'unsafe'), ('repo/Shaders/link', None), ('/absolute', b'unsafe')]:
                make_archive(archive, [entry])
                with self.assertRaises(ValueError):
                    c.unpack(archive, source)
            self.assertEqual(list(source.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
