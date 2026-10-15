import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('amx_compat', ROOT/'toolbox/helpers/antimicrox_compat.py')
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


class CompatibilityTests(unittest.TestCase):
    def test_payload_installs_and_repairs_damaged_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'register.so'
            compat.install(target)
            original = target.read_bytes()
            self.assertEqual(original[:4], b'\x7fELF')
            target.write_bytes(b'damaged')
            compat.install(target)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(Path(folder).glob('.xml-reader-*')), [])

    def test_bad_payload_does_not_replace_existing_library(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'register.so'; target.write_bytes(b'previous')
            payload = Path(folder)/'bad.b64'; payload.write_text('YmFk')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                compat.install(target, payload)
            self.assertEqual(target.read_bytes(), b'previous')
