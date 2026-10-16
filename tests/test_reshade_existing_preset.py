import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'toolbox/helpers'))
import reshade_existing_preset as e
import reshade_manager as manager


def dll():
    data=bytearray(200);data[:2]=b'MZ';data[60:64]=(64).to_bytes(4,'little')
    data[64:68]=b'PE\0\0';data[68:70]=(0x8664).to_bytes(2,'little')
    data.extend("crosire's ReShade post-processing injector".encode('utf-16le'));return bytes(data)


class ExistingPresetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.home=self.base/'home';self.rom=self.base/'Game.wine'
        self.folder=self.rom/'drive_c/game';self.folder.mkdir(parents=True)
        (self.folder/'dxgi.dll').write_bytes(dll())
        (self.folder/'Shaders').mkdir();(self.folder/'Shaders/CRT.fx').write_text('existing shader')
        self.ini=b'[GENERAL]\nEffectSearchPaths=.\\Shaders\\**\nPresetPath=.\\Old.ini\nPerformanceMode=1\n[INPUT]\nKeyOverlay=36,0,0,0\n'
        (self.folder/'ReShade.ini').write_bytes(self.ini)
        (self.folder/'Old.ini').write_text('Techniques=Old\n')
        self.source=self.base/'download.ini';self.source.write_text('Techniques=CRT@CRT.fx\n[CRT.fx]\nAmount=1\n')

    def test_directory_import_preserves_injector_shaders_and_restores_exact_config(self):
        before={p.relative_to(self.rom):p.read_bytes() for p in self.rom.rglob('*') if p.is_file()}
        e.configure(self.home,self.rom,'drive_c/game',self.source)
        config=manager.read_json(e.config_path(self.home,self.rom))
        preset=self.folder/config['filename']
        self.assertEqual(preset.read_bytes(),self.source.read_bytes())
        current=(self.folder/'ReShade.ini').read_text()
        self.assertIn('EffectSearchPaths=.\\Shaders\\**',current)
        self.assertIn('PerformanceMode=1',current)
        self.assertIn('PresetPath=.\\'+config['filename'],current)
        self.assertEqual((self.folder/'dxgi.dll').read_bytes(),before[Path('drive_c/game/dxgi.dll')])
        self.assertEqual((self.folder/'Shaders/CRT.fx').read_text(),'existing shader')
        e.restore(self.home,self.rom)
        self.assertEqual(before,{p.relative_to(self.rom):p.read_bytes() for p in self.rom.rglob('*') if p.is_file()})

    def test_live_game_and_symlink_are_refused_before_replacing_files(self):
        with patch.object(e,'ensure_idle',side_effect=ValueError('running')):
            with self.assertRaisesRegex(ValueError,'running'):e.configure(self.home,self.rom,'drive_c/game',self.source)
        self.assertFalse(e.config_path(self.home,self.rom).exists())
        outside=self.base/'outside.ini';outside.write_text('private')
        (self.folder/'ReShade.ini').unlink();(self.folder/'ReShade.ini').symlink_to(outside)
        with self.assertRaises(ValueError):e.configure(self.home,self.rom,'drive_c/game',self.source)
        self.assertEqual(outside.read_text(),'private')
        self.assertFalse(e.config_path(self.home,self.rom).exists())

    def test_unreadable_configuration_does_not_register_a_persistent_launch_rule(self):
        (self.folder/'ReShade.ini').write_bytes(b'\xff\xfeinvalid')
        with self.assertRaises(UnicodeError):e.configure(self.home,self.rom,'drive_c/game',self.source)
        self.assertFalse(e.config_path(self.home,self.rom).exists())
        self.assertEqual((self.folder/'ReShade.ini').read_bytes(),b'\xff\xfeinvalid')

    def test_hook_keeps_in_game_edits_and_does_not_overwrite_on_relaunch(self):
        e.configure(self.home,self.rom,'drive_c/game',self.source)
        config=manager.read_json(e.config_path(self.home,self.rom));preset=self.folder/config['filename']
        changed=b'Techniques=CRT@CRT.fx\n[CRT.fx]\nAmount=0.5\n';preset.write_bytes(changed)
        manager.event(self.home,self.rom,'gameStop')
        manager.event(self.home,self.rom,'gameStart')
        self.assertEqual(preset.read_bytes(),changed)
        self.assertEqual(e.source_path(self.home,self.rom).read_bytes(),changed)
        with self.assertRaisesRegex(ValueError,'edited'):e.restore(self.home,self.rom)
        self.assertEqual(preset.read_bytes(),changed)

    @unittest.skipUnless(shutil.which('mksquashfs') and shutil.which('unsquashfs'),'squashfs-tools required')
    def test_archive_import_and_new_runner_hook_modify_only_upperdir_ini_files(self):
        archive=self.base/'Game.wsquashfs'
        subprocess.run(['mksquashfs',str(self.rom),str(archive),'-noappend','-quiet','-processors','1'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        original=hashlib.sha256(archive.read_bytes()).hexdigest();bottles=self.base/'bottles'
        read_text=Path.read_text
        def launcher(path,*args,**kwargs):
            return 'mount -t overlay upperdir=' if str(path)=='/usr/bin/batocera-wine' else read_text(path,*args,**kwargs)
        with patch.object(Path,'read_text',launcher):
            e.configure(self.home,archive,'drive_c/game',self.source,'Runner1',bottles)
        first=bottles/'Runner1'/(archive.name+'.wine')
        config=manager.read_json(e.config_path(self.home,archive))
        self.assertEqual((first/'drive_c/game'/config['filename']).read_bytes(),self.source.read_bytes())
        self.assertEqual(len([p for p in first.rglob('*') if p.is_file()]),2)
        manager.event(self.home,archive,'gameStart','Runner2',bottles)
        second=bottles/'Runner2'/(archive.name+'.wine')
        self.assertEqual((second/'drive_c/game'/config['filename']).read_bytes(),self.source.read_bytes())
        e.restore(self.home,archive)
        self.assertFalse(list(first.rglob('*.ini')));self.assertFalse(list(second.rglob('*.ini')))
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),original)


if __name__=='__main__':unittest.main()
