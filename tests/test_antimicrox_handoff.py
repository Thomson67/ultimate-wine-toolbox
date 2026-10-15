import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import antimicrox_handoff as handoff
from antimicrox_live import LiveSession


class Clock:
    def __init__(self): self.now = 0
    def time(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Api:
    def __init__(self, states):
        self.states = list(states); self.last = self.states[-1]; self.launches = []; self.calls = []
    def running(self):
        if self.states: self.last = self.states.pop(0)
        self.calls.append(('running', self.last))
        return self.last
    def launch(self, rom):
        self.launches.append(rom); self.calls.append(('launch', rom))


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); root = self.base/'windows'; root.mkdir()
        self.rom = root/'Game [GE].wsquashfs'; self.rom.touch()
        self.session = LiveSession(self.base/'home', root)
        self.data = self.session.prepare(self.rom)
        self.clock = Clock(); self.stopped = []

    def worker(self, api):
        worker = handoff.Handoff(self.session, str(self.rom), api, self.clock.time,
                                  self.clock.sleep, idle_timeout=1, start_timeout=1)
        worker.stop_mapping = lambda: self.stopped.append(str(self.rom))
        return worker

    def test_original_deadlock_waits_for_ports_exit_and_confirms_exact_target(self):
        api = Api([(200, handoff.TOOLBOX), (201, ''),
                   (200, handoff.TOOLBOX), (200, str(self.rom)),
                   (200, str(self.rom)), (201, ''), (201, '')])
        self.assertEqual(self.worker(api).run(), 'short')
        self.assertEqual(api.calls[:3], [('running', (200, handoff.TOOLBOX)),
                                        ('running', (201, '')), ('launch', str(self.rom))])
        self.assertEqual(api.launches, [str(self.rom), handoff.TOOLBOX])
        self.assertEqual(self.stopped, [str(self.rom)])
        self.assertFalse(Path(self.data['keys']).exists())
        self.assertEqual((self.session.home/'state/resume-wsq.request').read_text(), 'antimicrox\n')

    def test_ports_status_200_is_never_treated_as_a_running_target(self):
        api = Api([(200, handoff.TOOLBOX)])
        self.assertEqual(self.worker(api).run(), 'launch_failed')
        self.assertEqual(api.launches, [])
        self.assertIn('not released', self.session.read()['error'])
        self.assertFalse(Path(self.data['keys']).exists())

    def test_already_queued_target_is_attached_without_duplicate_launch(self):
        api = Api([(200, str(self.rom)), (201, ''), (201, '')])
        self.worker(api).run()
        self.assertEqual(api.launches, [handoff.TOOLBOX])

    def test_another_game_is_never_interrupted_or_replaced_by_menu(self):
        api = Api([(201, ''), (200, '/games/different.wine')])
        self.assertEqual(self.worker(api).run(), 'launch_failed')
        self.assertEqual(api.launches, [str(self.rom)])
        self.assertIn('different game', self.session.read()['error'])

    def test_empty_or_unavailable_status_does_not_confirm_start(self):
        api = Api([(201, ''), (200, ''), (None, ''), (201, '')])
        self.assertEqual(self.worker(api).run(), 'launch_failed')
        self.assertIn('not confirmed', self.session.read()['error'])
        self.assertFalse(Path(self.data['keys']).exists())

    def test_replaced_session_is_not_stopped_or_restored_by_old_observer(self):
        api = Api([(200, handoff.TOOLBOX)])
        worker = self.worker(api)
        original = self.session.read(); original['session_id'] = 'new-session'
        self.session.write(original)
        worker.run()
        self.assertEqual(api.launches, [])
        self.assertEqual(self.stopped, [])
        self.assertEqual(self.session.read()['phase'], 'prepared')
        self.assertTrue(Path(self.data['keys']).exists())

    def test_stop_timeout_does_not_skip_shortcut_restoration(self):
        api = Api([(200, str(self.rom)), (201, ''), (201, '')])
        worker = self.worker(api)
        worker.stop_mapping = lambda: (_ for _ in ()).throw(subprocess.TimeoutExpired('hook', 10))
        worker.run()
        self.assertFalse(Path(self.data['keys']).exists())
        self.assertEqual(api.launches, [handoff.TOOLBOX])

    def test_spawn_is_detached_and_closes_inherited_descriptors(self):
        with patch.object(handoff, 'LOG_DIR', self.base/'logs'), \
             patch.object(handoff.subprocess, 'Popen', return_value=SimpleNamespace(pid=123)) as popen:
            handoff.spawn(self.session.home, str(self.rom))
            args, kwargs = popen.call_args
            self.assertIn('run', args[0])
            self.assertTrue(kwargs['start_new_session'])
            self.assertTrue(kwargs['close_fds'])
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)


class EsApiTests(unittest.TestCase):
    def test_running_api_reads_rom_path_instead_of_accepting_http_200_alone(self):
        response = SimpleNamespace(status=200, read=lambda: json.dumps({'path': handoff.TOOLBOX}).encode())
        context = SimpleNamespace()
        from unittest.mock import MagicMock
        context = MagicMock(); context.__enter__.return_value = response
        with patch.object(handoff.urllib.request, 'urlopen', return_value=context):
            self.assertEqual(handoff.EsApi().running(), (200, handoff.TOOLBOX))


if __name__ == '__main__':
    unittest.main()
