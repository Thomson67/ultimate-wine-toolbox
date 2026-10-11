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
            self.assertEqual(autorun.read_bytes(),b'ENV=FOO=bar\r\nCMD="Game.exe"\r\n')
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)

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
