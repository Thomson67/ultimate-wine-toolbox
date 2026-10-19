"""A confirmed ES return must release the previous Ports process and restore its lifecycle."""
import os
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
    def running(self):
        self.calls.append('running')
        return self.code, ''
    def indexed(self, rom):
        self.calls.append('indexed')
        return self.present
    def reload_games(self):
        self.calls.append('reload')
        self.present = True
    def launch(self, rom):
        self.calls.append('launch')
        self.launches += 1
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

    def test_busy_parent_retains_request_without_touching_es(self):
        api = Api(self.request)
        self.assertFalse(self.run_return(api, lambda pid: True))
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
