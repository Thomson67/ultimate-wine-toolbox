"""A confirmed ES return must release the previous Ports process and restore its lifecycle."""
import os
import fcntl
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import toolbox_return as helper


class Clock:
    def __init__(self): self.now = 0
    def clock(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Api:
    def __init__(self, request, indexed=True, consume_on=1):
        self.request = request
        self.present = indexed
        self.consume_on = consume_on
        self.calls = []
        self.code = 201
        self.launches = 0
        self.targets = []
    def running(self):
        self.calls.append('running')
        return self.code, ''
    def indexed(self, rom, system=None):
        self.calls.append('indexed')
        return self.present
    def reload_games(self):
        self.calls.append('reload')
        self.present = True
    def launch(self, rom):
        self.calls.append('launch')
        self.launches += 1
        self.targets.append(rom)
        if self.launches == self.consume_on: self.request.unlink()


class ToolboxReturnTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / 'state').mkdir()
        self.request = self.home / 'state/resume-wsq.request'; self.request.touch()
        self.time = Clock()

    def run_return(self, api, alive=lambda pid: False):
        return helper.resume(self.home, 123, api, self.time.clock, self.time.sleep,
                             alive, timeout=1, refresh_timeout=1, confirm_timeout=1)

    def test_parent_release_precedes_any_es_request(self):
        api = Api(self.request)
        def alive(pid):
            self.assertEqual(api.calls, [])
            return self.time.now < .5
        self.assertTrue(self.run_return(api, alive))
        self.assertFalse(self.request.exists())
        self.assertEqual(api.launches, 1)

    def test_reshade_game_launch_waits_for_ports_and_returns_after_game_stop(self):
        self.request.unlink()
        rom = '/userdata/roms/windows/My Game.wsquashfs'
        states = iter([(201, '')] * 4 + [(200, rom), (200, rom), (201, '')])
        api = Api(self.request)
        def running():
            self.assertGreaterEqual(self.time.now, .5)
            return next(states)
        api.running = running
        api.launch = api.targets.append
        with patch.object(helper, 'resume', return_value=True) as resume:
            self.assertTrue(helper.run_reshade_preset(
                self.home, 123, rom, api, self.time.clock, self.time.sleep,
                lambda pid: self.time.now < .5))
        self.assertEqual(api.targets, [rom])
        self.assertEqual(self.request.read_text(), 'reshade-preset\n')
        self.assertEqual((self.home/'state/reshade-preset.result').read_text(), f'{rom}\nok\n')
        resume.assert_called_once()

    def test_reshade_missing_game_returns_with_error_without_launching(self):
        self.request.unlink()
        rom = '/userdata/roms/windows/Missing.wine'
        api = Api(self.request, indexed=False)
        with patch.object(helper, 'resume', return_value=True) as resume:
            self.assertTrue(helper.run_reshade_preset(
                self.home, 123, rom, api, self.time.clock, self.time.sleep,
                lambda pid: False))
        self.assertEqual(api.targets, [])
        self.assertEqual((self.home/'state/reshade-preset.result').read_text(), f'{rom}\nlaunch_failed\n')
        resume.assert_called_once()

    def test_busy_parent_retains_request_without_touching_es(self):
        api = Api(self.request)
        self.assertFalse(self.run_return(api, lambda pid: True))
        self.assertEqual(api.calls, [])
        self.assertTrue(self.request.exists())

    def test_shared_lock_prevents_two_workflows_from_launching_toolbox(self):
        api = Api(self.request)
        with (self.home/'state/toolbox-return.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertFalse(self.run_return(api))
        self.assertEqual(api.calls, [])
        self.assertTrue(self.request.exists())

    def test_missing_port_is_reindexed_before_launch(self):
        api = Api(self.request, indexed=False)
        self.assertTrue(self.run_return(api))
        self.assertLess(api.calls.index('reload'), api.calls.index('launch'))
        self.assertEqual(api.calls.count('reload'), 1)

    def test_unknown_port_does_not_open_a_direct_terminal(self):
        api = Api(self.request, indexed=False)
        api.reload_games = lambda: None
        self.assertFalse(self.run_return(api))
        self.assertEqual(api.launches, 0)
        self.assertTrue(self.request.exists())

    def test_http_acknowledgement_without_consumption_is_retried(self):
        api = Api(self.request, consume_on=2)
        self.assertTrue(self.run_return(api))
        self.assertEqual(api.launches, 2)

    def test_ignored_requests_keep_recovery_state(self):
        api = Api(self.request, consume_on=10)
        self.assertFalse(self.run_return(api))
        self.assertEqual(api.launches, 3)
        self.assertTrue(self.request.exists())

    def test_busy_es_never_receives_a_launch(self):
        api = Api(self.request); api.code = 200
        self.assertFalse(self.run_return(api))
        self.assertEqual(api.launches, 0)
        self.assertTrue(self.request.exists())

    def test_game_started_after_refresh_prevents_toolbox_launch(self):
        api = Api(self.request, indexed=False)
        def refresh(): api.present = True; api.code = 200
        api.reload_games = refresh
        self.assertFalse(self.run_return(api))
        self.assertEqual(api.launches, 0)

    def test_grouped_ports_uses_owned_child_without_changing_global_grouping(self):
        api = Api(self.request)
        api.system_info = lambda name: dict(groupsystem='true')
        target = str(self.home/'runtime/proxy.sh')
        with patch.object(helper, 'ensure_proxy', return_value=('uwt_return', target, True)) as create:
            self.assertTrue(self.run_return(api))
        create.assert_called_once_with(self.home, report_changes=True)
        self.assertEqual(api.targets, [target])
        self.assertEqual(api.calls.count('reload'), 1)

    def test_existing_grouped_proxy_is_reused_without_reload(self):
        api = Api(self.request)
        api.system_info = lambda name: dict(groupsystem=True)
        target = str(self.home/'runtime/proxy.sh')
        with patch.object(helper,'ensure_proxy',return_value=('uwt_return',target,False)):
            self.assertTrue(self.run_return(api))
        self.assertNotIn('reload',api.calls)
        self.assertEqual(api.launches,1)

    def test_existing_proxy_missing_from_es_index_is_refreshed(self):
        api = Api(self.request,indexed=False)
        api.system_info = lambda name: dict(groupsystem=True)
        target = str(self.home/'runtime/proxy.sh')
        with patch.object(helper,'ensure_proxy',return_value=('uwt_return',target,False)):
            self.assertTrue(self.run_return(api))
        self.assertEqual(api.calls.count('reload'),1)
        self.assertLess(api.calls.index('reload'),api.calls.index('launch'))

    def test_no_retry_while_toolbox_is_starting_without_consuming_request(self):
        api = Api(self.request,consume_on=10)
        def running():
            return (200,helper.TOOLBOX) if api.launches else (201,'')
        api.running = running
        self.assertFalse(self.run_return(api))
        self.assertEqual(api.launches,1)
        self.assertTrue(self.request.exists())

    def test_other_game_starting_after_request_prevents_further_launches(self):
        api = Api(self.request,consume_on=10)
        api.running = lambda: (200,'/games/Other.wine') if api.launches else (201,'')
        self.assertFalse(self.run_return(api))
        self.assertEqual(api.launches,1)
        self.assertTrue(self.request.exists())

    def test_return_journal_contains_monotonic_timings_and_http_acknowledgement(self):
        import io
        from contextlib import redirect_stdout
        api=Api(self.request)
        launch=api.launch
        def timed_launch(target):
            self.time.sleep(.3)
            launch(target)
            return 200
        api.launch=timed_launch
        output=io.StringIO()
        with redirect_stdout(output):self.assertTrue(self.run_return(api))
        self.assertIn('elapsed=',output.getvalue())
        self.assertIn('http=200 duration=0.300s',output.getvalue())
        self.assertIn('confirmed',output.getvalue())

    def test_ungrouped_ports_keeps_native_launch_without_creating_proxy(self):
        api = Api(self.request)
        api.system_info = lambda name: dict(groupsystem='false')
        with patch.object(helper, 'ensure_proxy') as create:
            self.assertTrue(self.run_return(api))
        create.assert_not_called()
        self.assertEqual(api.targets, [helper.TOOLBOX])

    def test_spawn_detaches_and_closes_inherited_descriptors(self):
        with patch.object(helper, 'LOG_DIR', self.home), patch.object(helper.subprocess, 'Popen') as popen:
            with patch.object(sys, 'argv', ['return', 'spawn', '--parent-pid', '123']):
                helper.main()
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertTrue(popen.call_args.kwargs['close_fds'])
        self.assertEqual(popen.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertIn('123', popen.call_args.args[0])

    def test_port_return_never_spawns_a_naked_terminal(self):
        source = (ROOT/'toolbox/ports/Ultimate Wine Toolbox.sh').read_text()
        resume = source.split('resume_wsquashfs_toolbox() {', 1)[1].split('\nlaunch_rom=""', 1)[0]
        self.assertIn('toolbox_return.py', resume)
        self.assertNotIn('/usr/bin/xterm', resume)
        self.assertIn('--parent-pid "$$"', resume)


if __name__ == '__main__':
    unittest.main()
