import hashlib
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import reshade_extra_shaders as e
import reshade_manager as r


class ExtraShaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base/'home'
        self.shaders = self.home/'reshade/runtime/game-shaders/example'
        self.shaders.mkdir(parents=True)
        self.sources = {'First.fx': b'#include "ReShade.fxh"\ntechnique First {}',
                        'Second.fx': b'#include "ReShade.fxh"\ntechnique Second {}'}
        self.entries = [{'file': name, 'sha256': e.digest(data), 'url':
                         'https://raw.githubusercontent.com/Author/Shaders/'+'a'*40+'/'+name}
                        for name, data in self.sources.items()]
        self.catalog = self.base/'catalog.json'
        self.catalog.write_text(json.dumps({'effects': self.entries}))

    def tearDown(self):
        self.temp.cleanup()

    def download(self, args, **kwargs):
        name = args[args.index('-o')-1].split('/')[-1]
        Path(args[args.index('-o')+1]).write_bytes(self.sources[name])

    def test_selected_extras_download_once_and_keep_provenance(self):
        with patch.object(e.subprocess, 'run', side_effect=self.download) as download:
            e.install(self.home, self.shaders, self.catalog)
            self.assertEqual(download.call_count, 2)
        for name, data in self.sources.items():
            self.assertEqual((self.shaders/'Merged/Shaders'/name).read_bytes(), data)
        provenance = r.read_json(self.shaders/'uwt-extra-shaders.json')
        self.assertEqual(provenance['files']['First.fx']['sha256'], self.entries[0]['sha256'])
        with patch.object(e.subprocess, 'run', side_effect=AssertionError('cache redownload')):
            e.install(self.home, self.shaders, self.catalog)

    def test_checksum_failure_changes_no_merged_effects(self):
        def bad_download(args, **kwargs):
            self.download(args, **kwargs)
            if 'Second.fx' in args[args.index('-o')-1]:
                Path(args[args.index('-o')+1]).write_bytes(b'corrupt download')
        with patch.object(e.subprocess, 'run', side_effect=bad_download):
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                e.install(self.home, self.shaders, self.catalog)
        self.assertFalse((self.shaders/'Merged/Shaders/First.fx').exists())
        self.assertFalse((self.shaders/'uwt-extra-shaders.json').exists())

    def test_local_edits_and_links_are_preserved(self):
        with patch.object(e.subprocess, 'run', side_effect=self.download):
            e.install(self.home, self.shaders, self.catalog)
        target = self.shaders/'Merged/Shaders/First.fx'
        target.write_bytes(b'user edit')
        with self.assertRaisesRegex(ValueError, 'edited'):
            e.install(self.home, self.shaders, self.catalog)
        self.assertEqual(target.read_bytes(), b'user edit')
        target.unlink()
        shared = self.base/'shared.fx';shared.write_bytes(b'shared shader')
        target.symlink_to(shared)
        with self.assertRaisesRegex(ValueError, 'collides'):
            e.install(self.home, self.shaders, self.catalog)
        self.assertEqual(shared.read_bytes(), b'shared shader')

    def test_backend_selection_excludes_only_supplement(self):
        self.assertEqual(e.backend_packs('reshade-shaders,uwt-retro-extras,guestrr-shaders'),
                         'reshade-shaders,guestrr-shaders')
        self.assertEqual(e.backend_packs('uwt-retro-extras'), 'none')
        self.assertEqual(e.backend_packs('sweetfx-shaders'), 'sweetfx-shaders')
        with self.assertRaises(ValueError):
            e.backend_packs('bad;selection')

    def test_backend_selection_cli_needs_no_userdata_directory(self):
        home = self.base/'not-created'
        result=subprocess.run([sys.executable,str(ROOT/'toolbox/helpers/reshade_manager.py'),
                               '--home',str(home),'backend-packs','sweetfx-shaders,uwt-retro-extras'],
                              capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'sweetfx-shaders\n')
        self.assertFalse(home.exists())

    def test_bundled_5xbr_retains_original_content_and_needs_no_download(self):
        entry=next(v for v in json.loads(e.CATALOG.read_text())['effects'] if v.get('bundled'))
        self.catalog.write_text(json.dumps({'effects':[entry]}))
        with patch.object(e.subprocess,'run',side_effect=AssertionError('bundled shader downloaded')):
            e.install(self.home,self.shaders,self.catalog)
        source=(e.BUNDLED/entry['file']).read_bytes()
        self.assertEqual((self.shaders/'Merged/Shaders'/entry['file']).read_bytes(),source)
        self.assertEqual(e.digest(source),entry['sha256'])
        self.assertIn(b'Ported by spiderh',source)
        self.assertIn(b'GNU General Public License',source)
        entry['bundled']='../outside.fx'
        self.catalog.write_text(json.dumps({'effects':[entry]}))
        with self.assertRaisesRegex(ValueError,'bundled extra shader path'):
            e.install(self.home,self.shaders,self.catalog)

    def test_finish_validates_backend_packs_before_adding_requested_supplement(self):
        rom = self.base/'Game.wine';rom.mkdir()
        workspace = self.home/'reshade/workspaces'/r.key(rom);workspace.mkdir(parents=True)
        cache = self.home/'reshade/runtime';cache.mkdir(exist_ok=True)
        binary = bytearray(200);binary[:2]=b'MZ';binary[60:64]=(64).to_bytes(4,'little')
        binary[64:68]=b'PE\0\0';binary[68:70]=(0x8664).to_bytes(2,'little')
        dll=cache/'dxgi.dll';compiler=cache/'compiler.dll'
        dll.write_bytes(binary);compiler.write_bytes(binary)
        (workspace/'dxgi.dll').symlink_to(dll)
        (workspace/'d3dcompiler_47.dll').symlink_to(compiler)
        (workspace/'ReShade_shaders').symlink_to(self.shaders)
        pending={'rom':str(rom),'exe':'Game.exe','dll':'dxgi','arch':64,'version':'6.8.0',
                 'repos':'sweetfx-shaders,uwt-retro-extras','state_key':'example'}
        r.save_json(workspace/'pending.json',pending)
        state=cache/'game-state/example.state';state.parent.mkdir();state.write_text('selected_repos=sweetfx-shaders\n')
        with patch.dict(r.COMPILER_HASH,{64:e.digest(bytes(binary))}), patch.object(e,'install') as install:
            cfg=r.finish(self.home,rom)
            install.assert_called_once_with(self.home,self.shaders)
        self.assertEqual(cfg['repos'],pending['repos'])
        state.write_text('selected_repos=\n')
        with patch.dict(r.COMPILER_HASH,{64:e.digest(bytes(binary))}),patch.object(e,'install') as install:
            with self.assertRaisesRegex(ValueError,'not all requested'):
                r.finish(self.home,rom)
            install.assert_not_called()
