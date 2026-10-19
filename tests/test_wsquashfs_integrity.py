"""Integrity must read the data even when recent tools shorten their help output."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import wsquashfs_integrity as integrity


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.archive = self.base/"Marvel's Spider-Man 2.wsquashfs.update-tmp"
        self.archive.write_bytes(b'archive')
        self.log, self.cancel = self.base/'check.log', self.base/'cancel'
        self.calls = self.base/'calls.jsonl'
        self.tool = self.base/'unsquashfs'

    def configure(self, short, full='', data_code=0, help_code=0):
        self.tool.write_text(f'''#!{sys.executable}
import json, sys
from pathlib import Path
with Path({str(self.calls)!r}).open('a') as stream:
    stream.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1] in ('-help', '-help-all'):
    print({short!r} if sys.argv[1] == '-help' else {full!r}, file=sys.stderr)
    raise SystemExit({help_code})
if sys.argv[1] == '-pf':
    print('data read completed' if {data_code} == 0 else 'data block decompression failed', file=sys.stderr)
    raise SystemExit({data_code})
raise SystemExit(0)
''')
        self.tool.chmod(0o755)

    def check(self, mode='full'):
        return integrity.check(self.archive, mode, self.log, self.cancel, str(self.tool))

    def commands(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_recent_summary_help_falls_back_and_reads_all_data(self):
        self.configure('Run unsquashfs -help-all to see all sections', '\t-pf\t<file> output pseudo file')
        self.assertEqual(self.check(), 0)
        self.assertEqual(self.commands(), [['-help'], ['-help-all'], ['-s', str(self.archive)],
                                          ['-pf', '/dev/null', str(self.archive)]])
        self.assertIn('detected via -help-all', self.log.read_text())
        self.assertIn('data read completed', self.log.read_text())

    def test_old_help_is_supported_even_with_nonzero_help_exit(self):
        self.configure('-pf FILE output pseudo file', help_code=1)
        self.assertEqual(self.check(), 0)
        self.assertNotIn(['-help-all'], self.commands())
        self.assertEqual(self.commands()[-1], ['-pf', '/dev/null', str(self.archive)])

    def test_long_alias_with_newline_is_detected(self):
        self.configure('-pseudo-file\nFILE output pseudo file')
        self.assertEqual(self.check(), 0)

    def test_missing_capability_keeps_unsupported_result_and_help_diagnostics(self):
        self.configure('Unknown -help-all option', '-pf-other is not pseudo-file output', help_code=1)
        self.assertEqual(self.check(), 3)
        self.assertEqual(self.commands(), [['-help'], ['-help-all']])
        self.assertIn('Archive data was not checked', self.log.read_text())
        self.assertIn('Unknown -help-all option', self.log.read_text())

    def test_corrupt_data_after_successful_probe_is_still_an_error(self):
        self.configure('Use -help-all', '-pf <file>', data_code=2)
        self.assertEqual(self.check(), 1)
        self.assertIn('data block decompression failed', self.log.read_text())
        self.assertIn('Result code: 2', self.log.read_text())

    def test_quick_check_does_not_probe_or_read_file_data(self):
        self.configure('')
        self.assertEqual(self.check('quick'), 0)
        self.assertEqual(self.commands(), [['-s', str(self.archive)], ['-ll', str(self.archive)]])

    def test_cancelled_check_does_not_start_tool(self):
        self.configure('-pf FILE')
        self.cancel.touch()
        self.assertEqual(self.check(), 130)
        self.assertFalse(self.calls.exists())


if __name__ == '__main__':
    unittest.main()
