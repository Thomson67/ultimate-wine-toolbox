import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

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
    def indexed(self, rom): return True
    def reload_games(self): self.calls.append(('reload', None))
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

    def test_unknown_game_refreshes_once_after_ports_exit_before_launch(self):
        api = Api([(200, handoff.TOOLBOX), (201, ''), (201, ''), (201, ''),
                   (201, ''), (200, str(self.rom)), (201, ''), (201, '')])
        indexed = iter([False, False, True])
        api.indexed = lambda rom: next(indexed)
        self.assertEqual(self.worker(api).run(), 'short')
        self.assertEqual(api.calls.count(('reload', None)), 1)
        self.assertEqual(api.calls[:4], [('running', (200, handoff.TOOLBOX)),
                                        ('running', (201, '')), ('running', (201, '')),
                                        ('reload', None)])
        self.assertLess(api.calls.index(('reload', None)), api.calls.index(('launch', str(self.rom))))

    def test_indexed_game_is_launched_without_refresh(self):
        api = Api([(201, ''), (200, str(self.rom)), (201, ''), (201, '')])
        self.worker(api).run()
        self.assertNotIn(('reload', None), api.calls)

    def test_missing_game_after_refresh_restores_session_without_launching_it(self):
        api = Api([(201, '')]); api.indexed = lambda rom: False
        worker = self.worker(api); worker.refresh_timeout = 1
        self.assertEqual(worker.run(), 'launch_failed')
        self.assertEqual(api.calls.count(('reload', None)), 1)
        self.assertEqual(api.launches, [handoff.TOOLBOX])
        self.assertIn('refresh timed out', self.session.read()['error'])
        self.assertFalse(Path(self.data['keys']).exists())

    def test_another_game_during_refresh_is_not_interrupted(self):
        other = '/userdata/roms/windows/Other.wine'
        api = Api([(201, ''), (201, ''), (200, other)])
        api.indexed = lambda rom: False
        self.assertEqual(self.worker(api).run(), 'launch_failed')
        self.assertEqual(api.launches, [])
        self.assertFalse(Path(self.data['keys']).exists())

    def test_temporary_api_failure_during_refresh_can_recover(self):
        api = Api([(201, ''), (201, ''), (201, ''), (201, ''),
                   (200, str(self.rom)), (201, ''), (201, '')])
        with patch.object(api, 'indexed', side_effect=[False, TimeoutError(), True]):
            self.assertEqual(self.worker(api).run(), 'short')
        self.assertEqual(api.calls.count(('reload', None)), 1)

    def test_unavailable_initial_list_does_not_trigger_a_refresh(self):
        api = Api([(201, '')])
        with patch.object(api, 'indexed', side_effect=TimeoutError('ES unavailable')):
            self.assertEqual(self.worker(api).run(), 'launch_failed')
        self.assertNotIn(('reload', None), api.calls)
        self.assertNotIn(str(self.rom), api.launches)
        self.assertFalse(Path(self.data['keys']).exists())

    def test_failed_refresh_request_restores_session_without_launching_game(self):
        api = Api([(201, '')]); api.indexed = lambda rom: False
        with patch.object(api, 'reload_games', side_effect=OSError('reload failed')):
            self.assertEqual(self.worker(api).run(), 'launch_failed')
        self.assertEqual(api.launches, [handoff.TOOLBOX])
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
    def game_list(self, games):
        context = MagicMock()
        context.__enter__.return_value = SimpleNamespace(status=200, read=lambda: json.dumps(games).encode())
        return context

    def test_new_rom_is_missing_until_es_refreshes_its_in_memory_list(self):
        rom = '/userdata/roms/windows/Gobliins 6[L].wsquashfs'
        with patch.object(handoff.urllib.request, 'urlopen', side_effect=[
                self.game_list([{'path': rom + '.old'}]), self.game_list([{'path': rom}])]) as request:
            self.assertFalse(handoff.EsApi().indexed(rom))
            self.assertTrue(handoff.EsApi().indexed(rom))
        self.assertEqual(request.call_args.args[0], 'http://127.0.0.1:1234/systems/windows/games')

    def test_invalid_list_and_transport_errors_are_not_reported_as_unindexed(self):
        for payload in ({'error': 'busy'}, [{}], [None]):
            with self.subTest(payload=payload), patch.object(handoff.urllib.request, 'urlopen',
                                                             return_value=self.game_list(payload)):
                with self.assertRaises(ValueError):
                    handoff.EsApi().indexed('/userdata/roms/windows/Test.wine')
        with patch.object(handoff.urllib.request, 'urlopen', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                handoff.EsApi().indexed('/userdata/roms/windows/Test.wine')

    def test_running_api_reads_rom_path_instead_of_accepting_http_200_alone(self):
        response = SimpleNamespace(status=200, read=lambda: json.dumps({'path': handoff.TOOLBOX}).encode())
        context = SimpleNamespace()
        from unittest.mock import MagicMock
        context = MagicMock(); context.__enter__.return_value = response
        with patch.object(handoff.urllib.request, 'urlopen', return_value=context):
            self.assertEqual(handoff.EsApi().running(), (200, handoff.TOOLBOX))


if __name__ == '__main__':
    unittest.main()
