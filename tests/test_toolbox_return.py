"""ES queue acknowledgements must not be mistaken for a resumed Ports run."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'toolbox/ports/Ultimate Wine Toolbox.sh').read_text()
FUNCTION = 'launch_toolbox_confirmed() {' + SOURCE.split(
    'launch_toolbox_confirmed() {', 1)[1].split('\nresume_wsquashfs_toolbox()', 1)[0]


class ToolboxReturnTests(unittest.TestCase):
    def run_case(self, commands):
        with tempfile.TemporaryDirectory() as folder:
            script = r'''
BOOT_LOG="$BASE/log"; RESUME_REQUEST="$BASE/resume"; TOOLBOX_PORT='/ports/Toolbox.sh'
touch "$RESUME_REQUEST"
sleep() { :; }
get_running_game_http_code() { echo 201; }
''' + FUNCTION + '\n' + commands
            result = subprocess.run(['bash', '-u', '-c', script], capture_output=True,
                                    text=True, timeout=5, env=dict(os.environ, BASE=folder))
            self.assertEqual(result.returncode, 0, result.stderr)
            return (Path(folder) / 'log').read_text()

    def test_ignored_success_acknowledgement_retries_until_port_consumes_request(self):
        log = self.run_case(r'''
count=0
launch_game_via_es() {
 count=$((count+1))
 if [ "$count" -eq 2 ]; then rm "$RESUME_REQUEST"; fi
 return 0
}
launch_toolbox_confirmed || exit 1
[ "$count" -eq 2 ] || exit 2
''')
        self.assertIn('consumed_after_attempt=2', log)

    def test_unconsumed_request_is_failure_even_with_http_success(self):
        log = self.run_case(r'''
count=0
launch_game_via_es() { count=$((count+1)); return 0; }
launch_toolbox_confirmed
[ "$?" -eq 1 ] && [ "$count" -eq 3 ] && [ -f "$RESUME_REQUEST" ]
''')
        self.assertIn('not confirmed after three attempts', log)

    def test_busy_es_prevents_launch_and_retains_recovery_request(self):
        log = self.run_case(r'''
get_running_game_http_code() { echo 200; }
launch_game_via_es() { exit 9; }
launch_toolbox_confirmed
[ "$?" -eq 2 ] && [ -f "$RESUME_REQUEST" ]
''')
        self.assertIn('not confirmed idle', log)

    def test_started_session_without_consumed_request_is_not_relaunched(self):
        log = self.run_case(r'''
launch_game_via_es() { touch "$BASE/busy"; }
get_running_game_http_code() { if [ -f "$BASE/busy" ]; then echo 200; else echo 201; fi; }
launch_toolbox_confirmed
[ "$?" -eq 2 ] && [ -f "$RESUME_REQUEST" ]
''')
        self.assertIn('no duplicate launch', log)
        self.assertNotIn('wsq_resume_attempt=2', log)


if __name__ == '__main__':
    unittest.main()
