import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import reshade_diagnostic as d


class DiagnosticTests(unittest.TestCase):
    def process(self, proc, pid, prefix, maps, comm='GameThread'):
        p=proc/str(pid); p.mkdir()
        (p/'environ').write_bytes(b'WINEPREFIX='+os.fsencode(prefix)+b'\0')
        (p/'comm').write_text(comm+'\n')
        (p/'maps').write_text(maps)

    def test_only_target_prefix_and_windows_graphics_dlls(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); proc=p/'proc'; proc.mkdir(); game=p/'game.wine'; game.mkdir()
            self.process(proc, 1, game, '123 /usr/lib/libvulkan.so.1\n456 /game/d3d11.dll\n789 /game/dxgi.dll\n')
            self.process(proc, 2, p/'other.wine', '123 /game/d3d12.dll\n')
            self.process(proc, 3, game, '123 /game/opengl32.dll\n', 'wineboot.exe')
            evidence, names=d.scan(proc,[game])
            self.assertEqual(evidence, {'d3d11.dll','dxgi.dll'})
            self.assertEqual(names, {'GameThread'})

    def test_aliases_and_multiple_apis_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); proc=p/'proc';proc.mkdir();game=p/'game';game.mkdir();alias=p/'alias';alias.symlink_to(game)
            self.process(proc, 1, alias, '1 /wine/d3d9.dll.so\n2 /wine/d3d12.dll\n')
            self.assertEqual(d.scan(proc,[game])[0], {'d3d9.dll','d3d12.dll'})

    def test_posix_checksum_matches_umu_and_system_cksum(self):
        self.assertEqual(d.posix_cksum(b'compressed|30XX.wsquashfs|GE-Proton10-25-UMU'),517931436)
        for data in (b'', b'embedded|Game.wine|Runner', 'compressed|Jeu é [Wine].wsquashfs|GE-Proton'.encode()):
            expected = int(subprocess.check_output(['cksum'], input=data).split()[0])
            self.assertEqual(d.posix_cksum(data),expected)

    def test_umu_materialized_prefix_detects_live_d3d9_and_excludes_other_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);proc=p/'proc';proc.mkdir();runners=p/'runners'
            (runners/'GE-Proton10-25-UMU').mkdir(parents=True)
            compat=p/'compatdata';rom=p/'30XX.wsquashfs'
            candidates=d.targets(rom,p/'bottles',runners,compat)
            prefix=compat/'30XX.wsquashfs-517931436'/'pfx'
            self.assertIn(prefix,candidates)
            self.process(proc,1,prefix,'1 /prefix/drive_c/windows/system32/d3d9.dll\n', '30XX.exe')
            self.process(proc,2,compat/'30XX2.wsquashfs-517931436'/'pfx','1 /prefix/d3d12.dll\n')
            self.process(proc,3,compat/'30XX.wsquashfs-1234'/'pfx','1 /prefix/d3d11.dll\n')
            self.process(proc,4,prefix,'1 /prefix/opengl32.dll\n','xalia.exe')
            self.assertEqual(d.scan(proc,candidates),({'d3d9.dll'},{'30XX.exe'}))
            # A namespace may expose the prefix under a different path while
            # keeping STEAM_COMPAT_DATA_PATH at the exact adapter identity.
            (proc/'1/environ').write_bytes(b'WINEPREFIX=/namespace/pfx\0STEAM_COMPAT_DATA_PATH='+os.fsencode(prefix.parent)+b'\0')
            self.assertEqual(d.scan(proc,candidates),({'d3d9.dll'},{'30XX.exe'}))

    def test_umu_safe_names_and_wine_pc_anchors_match_the_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);runners=p/'runners';(runners/'Runner').mkdir(parents=True)
            for name,anchor in (('Jeu é.wine','Jeu é.wine'),('Game.pc','Game.pc'),('Game.pc','Game.pc.wine')):
                candidates=d.targets(p/name,p/'bottles',runners,p/'compat')
                stem=anchor[:-5] if anchor.endswith('.wine') else anchor
                safe=''.join(chr(b) if chr(b) in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' else '_' for b in os.fsencode(stem))
                crc=int(subprocess.check_output(['cksum'],input=os.fsencode(f'embedded|{anchor}|Runner')).split()[0])
                self.assertIn(p/'compat'/f'{safe}-{crc}'/'pfx',candidates)

    def test_observation_finishes_on_stop_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);proc=p/'proc';proc.mkdir();game=p/'Game.wine';game.mkdir(); stop=p/'stop';report=p/'report.json'
            self.process(proc, 1, game, '1 /game/d3d12.dll\n')
            def stop_after_sample(_): stop.touch()
            with patch.object(d.time, 'sleep', side_effect=stop_after_sample):
                d.observe(game,report,stop,proc=proc)
            result=json.loads(report.read_text())
            self.assertTrue(result['finished']); self.assertFalse(result['timed_out'])
            self.assertEqual(result['candidates'], ['dxgi'])
            self.assertEqual(result['evidence'], ['d3d12.dll'])

    def test_request_is_read_only_for_game_and_refuses_pending_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);home=p/'home';game=p/'Test [Runner].wine';game.mkdir()
            autorun=game/'autorun.cmd';autorun.write_bytes(b'ENV=FOO=bar\r\nCMD="Game.exe"\r\n')
            command=[sys.executable,str(ROOT/'toolbox/helpers/reshade_diagnostic.py'),'--home',str(home),'request',str(game)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((home/'state/launch-game.request').read_text(),str(game)+'\n')
            self.assertTrue((home/'state/restart-es.request').exists())
            self.assertEqual(autorun.read_bytes(),b'ENV=FOO=bar\r\nCMD="Game.exe"\r\n')
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)

    def test_pending_es_handoff_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);home=p/'home';game=p/'Game.wine';game.mkdir()
            state=home/'state';state.mkdir(parents=True)
            (state/'restart-es.request').write_text('existing request')
            command=[sys.executable,str(ROOT/'toolbox/helpers/reshade_diagnostic.py'),'--home',str(home),'request',str(game)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((state/'launch-game.request').exists())
            self.assertFalse((state/'reshade-diagnostic.json').exists())
            self.assertEqual((state/'restart-es.request').read_text(),'existing request')

    def test_installation_executable_is_saved_for_resume_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);game=p/'Game.wine';game.mkdir();home=p/'home'
            command=[sys.executable,str(ROOT/'toolbox/helpers/reshade_diagnostic.py'),'--home',str(home),'--exe']
            result=subprocess.run(command+['../Other.exe','request',str(game)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((home/'state/reshade-diagnostic.json').exists())
            exe='drive_c/game/Folder with spaces/Game.exe'
            result=subprocess.run(command+[exe,'request',str(game)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            data=json.loads((home/'state/reshade-diagnostic.json').read_text())
            self.assertEqual(data,{'rom':str(game),'installation_exe':exe})

    def test_port_stops_observer_before_resuming(self):
        source=(ROOT/'toolbox/ports/Ultimate Wine Toolbox.sh').read_text()
        function=source.split('monitor_wsq_launch() {',1)[1].split('\nresume_wsq_unavailable()',1)[0]
        # Stub the observer process and ES API; exercise the actual handoff function.
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'reshade-diagnostic.json').touch()
            script='''STATE_DIR="$BASE"; DIAG_REQUEST="$BASE/reshade-diagnostic.json"; BOOT_LOG="$BASE/log"; RESULT_FILE="$BASE/result"; launch_rom=Game.wine
python3() { while [ ! -e "$STATE_DIR/reshade-diagnostic.stop" ]; do sleep .01; done; printf stopped > "$BASE/observer"; }
launch_game_via_es() { return 0; }
wait_for_game_start() { GAME_STARTED_AT=$SECONDS; }
wait_for_game_stop() { return 0; }
resume_wsquashfs_toolbox() { [ -e "$BASE/observer" ] && printf resumed > "$BASE/resume"; }
monitor_wsq_launch() {'''+function+'\nmonitor_wsq_launch\n'
            result=subprocess.run(['bash','-c',script],env=dict(os.environ,BASE=str(p)),capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((p/'result').read_text(),'short\n')
            self.assertEqual((p/'resume').read_text(),'resumed')
